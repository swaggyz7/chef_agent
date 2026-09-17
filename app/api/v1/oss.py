"""阿里云 OSS 图片上传接口，并提供无 Key 时的本地开发降级方案。"""
from __future__ import annotations

import os
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.common.logger import logger
from app.models.schemas import (
    OssUploadResponse,
    PresignRequest,
    PresignResponse,
)

router = APIRouter(prefix="/oss", tags=["oss"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_DIR = PROJECT_ROOT / "app" / "static" / "uploads"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
MAX_IMAGE_SIZE = 10 * 1024 * 1024
PRESIGN_EXPIRES_SECONDS = 15 * 60


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _oss_settings() -> dict[str, str]:
    return {
        "access_key_id": _env("OSS_ACCESS_KEY_ID"),
        "access_key_secret": _env("OSS_ACCESS_KEY_SECRET"),
        "bucket": _env("OSS_BUCKET"),
        "region": _env("OSS_REGION", "cn-hangzhou"),
        "endpoint": _env("OSS_ENDPOINT", "oss-cn-hangzhou.aliyuncs.com"),
        "public_base_url": _env("OSS_PUBLIC_BASE_URL"),
    }


def _oss_configured(settings: dict[str, str] | None = None) -> bool:
    settings = settings or _oss_settings()
    return all(
        settings[name]
        for name in ("access_key_id", "access_key_secret", "bucket")
    )


def _safe_extension(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    return extension if extension in ALLOWED_EXTENSIONS else ".jpg"


def _object_key(filename: str) -> str:
    extension = _safe_extension(filename)
    return f"recipes/{uuid.uuid4().hex[:8]}/{uuid.uuid4().hex}{extension}"


def _public_file_url(settings: dict[str, str], object_key: str) -> str:
    if settings["public_base_url"]:
        return f"{settings['public_base_url'].rstrip('/')}/{quote(object_key)}"

    endpoint = settings["endpoint"].replace("https://", "").replace("http://", "")
    endpoint = endpoint.rstrip("/")
    return f"https://{settings['bucket']}.{endpoint}/{quote(object_key)}"


@router.get("/status")
async def oss_status() -> dict[str, object]:
    """查看 OSS 是否已配置；未配置时前端会使用本地上传。"""
    settings = _oss_settings()
    configured = _oss_configured(settings)
    return {
        "configured": configured,
        "bucket": settings["bucket"] if configured else "",
        "region": settings["region"],
        "endpoint": settings["endpoint"],
        "local_fallback": not configured,
    }


@router.post("/presign", response_model=PresignResponse)
async def create_presigned_upload(request: PresignRequest) -> PresignResponse:
    """生成浏览器直传 OSS 所需的签名 URL。"""
    settings = _oss_settings()
    if not _oss_configured(settings):
        raise HTTPException(
            status_code=503,
            detail="阿里云 OSS 尚未配置，请填写 OSS_ACCESS_KEY_ID、OSS_ACCESS_KEY_SECRET 和 OSS_BUCKET。",
        )

    if not request.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="当前接口仅支持图片文件。")

    try:
        import alibabacloud_oss_v2 as oss
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="缺少 alibabacloud-oss-v2，请先执行依赖安装。",
        ) from exc

    object_key = _object_key(request.filename)
    credentials_provider = oss.credentials.StaticCredentialsProvider(
        access_key_id=settings["access_key_id"],
        access_key_secret=settings["access_key_secret"],
    )
    config = oss.config.load_default()
    config.credentials_provider = credentials_provider
    config.region = settings["region"]
    config.endpoint = settings["endpoint"]
    client = oss.Client(config)

    try:
        result = client.presign(
            oss.PutObjectRequest(
                bucket=settings["bucket"],
                key=object_key,
                content_type=request.content_type,
            ),
            expires=timedelta(seconds=PRESIGN_EXPIRES_SECONDS),
        )
    except Exception as exc:  # pragma: no cover - 依赖远端 OSS 配置
        logger.exception("生成 OSS 上传签名失败")
        raise HTTPException(status_code=502, detail=f"生成 OSS 上传签名失败：{exc}") from exc

    headers = {"Content-Type": request.content_type}
    signed_headers = getattr(result, "signed_headers", None)
    if signed_headers:
        headers.update({str(key): str(value) for key, value in signed_headers.items()})

    return PresignResponse(
        upload_url=result.url,
        file_url=_public_file_url(settings, object_key),
        object_key=object_key,
        method=str(getattr(result, "method", "PUT") or "PUT"),
        headers=headers,
        expires_in=PRESIGN_EXPIRES_SECONDS,
    )


@router.post("/local-upload", response_model=OssUploadResponse)
async def local_upload(file: UploadFile = File(...)) -> OssUploadResponse:
    """本地开发上传，保证未填写阿里云配置时也能调试前端。"""
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 JPG、PNG、WEBP 或 GIF 图片。")

    data = await file.read(MAX_IMAGE_SIZE + 1)
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="图片不能超过 10 MB。")

    extension = _safe_extension(file.filename or "image.jpg")
    object_key = f"{uuid.uuid4().hex}{extension}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / object_key
    target.write_bytes(data)

    return OssUploadResponse(
        file_url=f"/static/uploads/{object_key}",
        object_key=f"local/{object_key}",
        storage="local",
    )