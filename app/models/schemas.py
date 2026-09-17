"""FastAPI 请求与响应数据模型。"""
from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """聊天请求。"""

    message: str = Field(min_length=1, max_length=8000)
    image_url: str | None = Field(default=None, max_length=4000)
    thread_id: str = Field(default="default", min_length=1, max_length=128)


class ChatMessage(BaseModel):
    """会话历史中的单条消息。"""

    role: Literal["user", "assistant"]
    content: str
    image_url: str | None = None


class ChatHistoryResponse(BaseModel):
    """会话历史响应。"""

    messages: list[ChatMessage]


class SourceItem(BaseModel):
    """菜谱参考来源。"""

    title: str = ""
    url: str = ""
    content: str = ""


class PresignRequest(BaseModel):
    """OSS 上传签名请求。"""

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="image/jpeg", max_length=100)


class PresignResponse(BaseModel):
    """OSS 上传签名响应。"""

    upload_url: str
    file_url: str
    object_key: str
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    expires_in: int = 900


class OssUploadResponse(BaseModel):
    """图片上传响应。"""

    file_url: str
    object_key: str
    storage: Literal["oss", "local"]


class DeleteResponse(BaseModel):
    """删除操作响应。"""

    success: bool = True


class RuntimeStatusResponse(BaseModel):
    """运行时配置状态。"""

    dashscope_configured: bool
    tavily_configured: bool
    oss_configured: bool
    model: str
    database: str