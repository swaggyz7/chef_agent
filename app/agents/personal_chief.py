"""AI 私厨核心 Agent：阿里百炼多模态模型 + Tavily + SQLite 记忆。"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_tavily import TavilySearch
from langgraph.checkpoint.sqlite import SqliteSaver

from app.common.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_DIR = PROJECT_ROOT / "db"
DB_PATH = DB_DIR / "personal_chief.db"

load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    """读取并清理环境变量。"""
    return (os.getenv(name) or default).strip()


DASHSCOPE_API_KEY = _env("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = _env(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
DASHSCOPE_MODEL = _env("DASHSCOPE_MODEL", "qwen3.5-plus")
TAVILY_API_KEY = _env("TAVILY_API_KEY")

if not DASHSCOPE_API_KEY:
    logger.warning("DASHSCOPE_API_KEY 尚未配置，聊天接口会返回配置提示。")
if not TAVILY_API_KEY:
    logger.warning("TAVILY_API_KEY 尚未配置，联网搜索工具将在调用时失败。")

# 占位值只用于保证服务在没有 Key 时也能正常启动。
model = init_chat_model(
    model=DASHSCOPE_MODEL,
    model_provider="openai",
    base_url=DASHSCOPE_BASE_URL,
    api_key=DASHSCOPE_API_KEY or "MISSING_DASHSCOPE_API_KEY",
)

tavily = TavilySearch(
    max_results=5,
    topic="general",
    api_key=TAVILY_API_KEY or "MISSING_TAVILY_API_KEY",
)
web_search = tavily

system_prompt = """
你是一名私人厨师。收到用户提供的食材照片或清单后，请按以下流程操作：
1.识别和评估食材：若用户提供照片，首先辨识所有可见食材。基于食材的外观状态，评估其新鲜度与可用量，整理出一份“当前可用食材清单”。
2.智能食谱检索：优先调用 web_search 工具，以“可用食材清单”为核心关键词，查找可行菜谱。
3.多维度评估与排序：从营养价值和制作难度两个维度对检索到的候选食谱进行量化打分，并根据得分排序，制作简单且营养丰富的排名靠前。
4.结构化方案输出：把排序后的食谱整理为一份结构清晰的建议报告，要包含食谱信息、得分、推荐理由、食谱的参考图片，帮助用户快速做出决策。

请严格按照流程，优先调用 web_search 工具搜索食谱，搜索不到的情况下才能自己发挥。
"""

DB_DIR.mkdir(parents=True, exist_ok=True)
connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
checkpointer = SqliteSaver(connection)
checkpointer.setup()

agent = create_agent(
    model=model,
    tools=[tavily],
    checkpointer=checkpointer,
    system_prompt=system_prompt,
)


def _content_to_text(content: Any) -> str:
    """把 LangChain 的字符串或内容块统一转换为文本。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            text = block.get("text")
            if text:
                parts.append(str(text))
    return "".join(parts)


def _human_message_to_parts(content: Any) -> tuple[str, str | None]:
    """提取用户消息中的文本和第一张图片地址。"""
    if isinstance(content, str):
        return content, None
    text = _content_to_text(content)
    image_url = None
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in {"image", "image_url"}:
                image_url = block.get("url") or block.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                break
    return text, image_url


async def search_recipes(
    prompt: str,
    image: str | None,
    thread_id: str,
) -> AsyncIterator[str]:
    """调用 Agent，并以流式方式输出模型回答。"""
    logger.info("[用户]: %s, image: %s, thread_id: %s", prompt, image, thread_id)

    if not DASHSCOPE_API_KEY:
        yield "阿里百炼 API Key 尚未配置。请在 .env 中填写 DASHSCOPE_API_KEY 后重试。"
        return

    if image and image.strip():
        message = HumanMessage(
            content=[
                {"type": "image", "url": image.strip()},
                {"type": "text", "text": prompt},
            ]
        )
    else:
        message = HumanMessage(content=prompt)

    try:
        async for chunk, _metadata in agent.astream(
            {"messages": [message]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode="messages",
        ):
            if isinstance(chunk, AIMessageChunk):
                text = _content_to_text(chunk.content)
                if text:
                    yield text
    except Exception as exc:  # pragma: no cover - 依赖外部服务错误
        logger.exception("Agent 调用失败")
        detail = str(exc).strip()
        yield (
            "信息检索失败，请检查 DASHSCOPE_API_KEY、TAVILY_API_KEY 和网络连接。"
            + (f"\n\n错误详情：{detail}" if detail else "")
        )


def clear_messages(thread_id: str) -> None:
    """清空指定会话。"""
    logger.info("清空历史消息，thread_id: %s", thread_id)
    delete_thread = getattr(checkpointer, "delete_thread", None)
    if callable(delete_thread):
        delete_thread(thread_id)
        return

    # 兼容不支持 delete_thread 的旧版本。
    cursor = connection.cursor()
    for table in ("writes", "checkpoints"):
        try:
            cursor.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
        except sqlite3.Error:
            continue
    connection.commit()


def _get_checkpoint(thread_id: str) -> Any:
    """兼容不同版本 SqliteSaver 的 checkpoint 读取结果。"""
    result = checkpointer.get({"configurable": {"thread_id": thread_id}})
    if hasattr(result, "checkpoint"):
        return result.checkpoint
    return result


def get_messages(thread_id: str) -> list[dict[str, str | None]]:
    """获取指定会话的历史消息。"""
    logger.info("获取历史消息，thread_id: %s", thread_id)
    checkpoint = _get_checkpoint(thread_id)
    if not checkpoint:
        return []

    channel_values = (
        checkpoint.get("channel_values")
        if isinstance(checkpoint, dict)
        else getattr(checkpoint, "channel_values", None)
    )
    if not channel_values:
        return []

    messages = channel_values.get("messages", [])
    result: list[dict[str, str | None]] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            text, image_url = _human_message_to_parts(message.content)
            if text or image_url:
                result.append({"role": "user", "content": text, "image_url": image_url})
        elif isinstance(message, AIMessage):
            text = _content_to_text(message.content)
            if text:
                result.append({"role": "assistant", "content": text, "image_url": None})
    return result


def runtime_status() -> dict[str, Any]:
    """返回当前运行配置状态。"""
    oss_configured = all(
        _env(name)
        for name in ("OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_BUCKET")
    )
    return {
        "dashscope_configured": bool(DASHSCOPE_API_KEY),
        "tavily_configured": bool(TAVILY_API_KEY),
        "oss_configured": oss_configured,
        "model": DASHSCOPE_MODEL,
        "database": str(DB_PATH.relative_to(PROJECT_ROOT)),
    }