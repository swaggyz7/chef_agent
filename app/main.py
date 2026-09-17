"""FastAPI 入口：配置路由、静态页面和运行时状态接口。"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.personal_chief import runtime_status
from app.api.v1 import chat, knowledge, memory, oss
from app.common.logger import setup_logging
from app.models.schemas import RuntimeStatusResponse

setup_logging()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PROJECT_ROOT / "app" / "static"

app = FastAPI(
    title="Personal Chief API",
    description="私厨：支持图片识别、本地菜品图谱 RAG、联网搜索、多轮对话和可选长期口味记忆。",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api/v1")
app.include_router(oss.router, prefix="/api/v1")
app.include_router(memory.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """返回前端聊天页面。"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    """容器和本地开发使用的健康检查。"""
    return {"status": "ok"}


@app.get("/api/v1/status", response_model=RuntimeStatusResponse)
async def status() -> RuntimeStatusResponse:
    """返回模型、搜索和 OSS 的配置状态。"""
    return RuntimeStatusResponse(**runtime_status())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, reload=True)