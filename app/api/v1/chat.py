"""对话与会话管理接口。"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents.personal_chief import clear_messages, get_messages, search_recipes
from app.models.schemas import ChatHistoryResponse, ChatRequest, DeleteResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def chat_endpoint(request: ChatRequest) -> StreamingResponse:
    """流式对话。"""
    return StreamingResponse(
        search_recipes(request.message, request.image_url, request.thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/messages", response_model=ChatHistoryResponse)
async def get_chat_messages(thread_id: str) -> ChatHistoryResponse:
    """获取历史消息。"""
    return ChatHistoryResponse(messages=get_messages(thread_id))


@router.delete("/messages", response_model=DeleteResponse)
async def clear_chat_messages(thread_id: str) -> DeleteResponse:
    """清空历史消息。"""
    clear_messages(thread_id)
    return DeleteResponse(success=True)