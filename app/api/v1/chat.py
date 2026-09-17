"""对话与会话管理接口。"""
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.agents.personal_chief import clear_messages, get_messages, search_recipes
from app.models.schemas import (
    CONTEXT_ID_PATTERN,
    ChatHistoryResponse,
    ChatRequest,
    DeleteResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])

CONTEXT_ID_QUERY = Query(
    min_length=8,
    max_length=128,
    pattern=CONTEXT_ID_PATTERN,
    description="匿名 context_id，用于隔离会话和长期记忆",
)


@router.post("/stream")
async def chat_endpoint(request: ChatRequest) -> StreamingResponse:
    """流式对话。"""
    return StreamingResponse(
        search_recipes(
            prompt=request.message,
            image=request.image_url,
            context_id=request.context_id,
            thread_id=request.thread_id,
            use_memory=request.use_memory,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/messages", response_model=ChatHistoryResponse)
async def get_chat_messages(
    context_id: str = CONTEXT_ID_QUERY,
    thread_id: str = Query(default="default", min_length=1, max_length=128),
) -> ChatHistoryResponse:
    """获取当前 context_id 下的历史消息。"""
    return ChatHistoryResponse(messages=get_messages(context_id, thread_id))


@router.delete("/messages", response_model=DeleteResponse)
async def clear_chat_messages(
    context_id: str = CONTEXT_ID_QUERY,
    thread_id: str = Query(default="default", min_length=1, max_length=128),
) -> DeleteResponse:
    """清空当前 context_id 下的历史消息。"""
    clear_messages(context_id, thread_id)
    return DeleteResponse(success=True)
