"""AI 私厨核心 Agent：多模态模型 + 搜索 + 会话记忆 + 可选长期口味记忆。"""
from __future__ import annotations

import os
import sqlite3
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from langgraph.checkpoint.sqlite import SqliteSaver

from app.common.logger import logger
from app.memory.store import CONSENT_VERSION, MemoryConsentError, memory_store

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


@dataclass(frozen=True)
class MemoryRuntimeContext:
    """当前请求可用的长期记忆授权上下文。"""

    context_id: str
    consent_version: str


_memory_context: ContextVar[MemoryRuntimeContext | None] = ContextVar(
    "personal_chief_memory_context",
    default=None,
)


@tool
def remember_taste_preference(category: str, value: str) -> str:
    """仅在用户明确要求记住长期口味偏好时保存。

    category 只能是 spicy_level、flavor、cuisine、liked_ingredient、
    disliked_ingredient、dietary_style、cooking_style、meal_preference。
    不要从照片、身份信息或普通闲聊中自行推断偏好，也不要保存姓名、联系方式、
    疾病、健康、宗教、政治或其他敏感信息。
    """
    request_context = _memory_context.get()
    if not request_context:
        return "长期记忆当前未开启，或者用户尚未完成隐私同意，本次没有保存任何内容。"

    try:
        preference = memory_store.add_preference(
            request_context.context_id,
            category=category,
            value=value,
            source="agent_explicit",
        )
    except MemoryConsentError:
        return "长期记忆当前未开启，或者用户已经撤回同意，本次没有保存任何内容。"
    except ValueError as error:
        return f"偏好没有保存：{error}"

    return (
        f"已记住：{preference['category_label']}为“{preference['value']}”。"
        "用户可以在“长期口味记忆”面板中查看或删除。"
    )


system_prompt = """
你是一名私人厨师。收到用户提供的食材照片或清单后，请按以下流程操作：
1.识别和评估食材：若用户提供照片，首先辨识所有可见食材。基于食材的外观状态，评估其新鲜度与可用量，整理出一份“当前可用食材清单”。
2.智能食谱检索：优先调用 web_search 工具，以“可用食材清单”为核心关键词，查找可行菜谱。
3.多维度评估与排序：从营养价值和制作难度两个维度对检索到的候选食谱进行量化打分，并根据得分排序，制作简单且营养丰富的排名靠前。
4.结构化方案输出：把排序后的食谱整理为一份结构清晰的建议报告，要包含食谱信息、得分、推荐理由、食谱的参考图片，帮助用户快速做出决策。

请严格按照流程，优先调用 web_search 工具搜索食谱，搜索不到的情况下才能自己发挥。

【长期记忆规则】
只有用户完成明确授权后，才可以使用长期口味偏好进行个性化推荐。
只有用户明确说“记住”“以后都按这个来”等持久化意图时，才允许调用 remember_taste_preference。
不得从照片、身份信息、一次性要求或普通闲聊中擅自推断和保存偏好。
不得保存姓名、电话、邮箱、账号、精确位置、疾病、健康、宗教、政治或其他敏感信息。
长期偏好只能作为辅助，用户本轮的明确要求始终优先。
"""

DB_DIR.mkdir(parents=True, exist_ok=True)
connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
checkpointer = SqliteSaver(connection)
checkpointer.setup()

agent = create_agent(
    model=model,
    tools=[tavily, remember_taste_preference],
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


def scoped_thread_id(context_id: str, thread_id: str) -> str:
    """把匿名 context 与会话 ID 组合，避免不同用户读取相同线程。"""
    return f"{context_id}::{thread_id}"


async def search_recipes(
    prompt: str,
    image: str | None,
    context_id: str,
    thread_id: str,
    use_memory: bool = False,
) -> AsyncIterator[str]:
    """调用 Agent，并以流式方式输出模型回答。"""
    logger.info(
        "[用户]: %s, image: %s, context_id: %s, thread_id: %s, use_memory: %s",
        prompt,
        image,
        context_id,
        thread_id,
        use_memory,
    )

    if not DASHSCOPE_API_KEY:
        yield "阿里百炼 API Key 尚未配置。请在 .env 中填写 DASHSCOPE_API_KEY 后重试。"
        return

    memory_active = bool(
        use_memory
        and context_id
        and memory_store.has_active_consent(context_id, CONSENT_VERSION)
    )
    memory_prompt = memory_store.build_prompt_context(context_id) if memory_active else ""
    request_system_prompt = system_prompt
    if memory_active:
        request_system_prompt = (
            f"{system_prompt}\n\n{memory_prompt}"
            if memory_prompt
            else f"{system_prompt}\n\n【长期记忆状态】用户已授权，但当前没有已保存的偏好。"
        )

    request_agent = (
        create_agent(
            model=model,
            tools=[tavily, remember_taste_preference],
            checkpointer=checkpointer,
            system_prompt=request_system_prompt,
        )
        if memory_active
        else agent
    )

    if image and image.strip():
        message = HumanMessage(
            content=[
                {"type": "image", "url": image.strip()},
                {"type": "text", "text": prompt},
            ]
        )
    else:
        message = HumanMessage(content=prompt)

    token = _memory_context.set(
        MemoryRuntimeContext(context_id, CONSENT_VERSION) if memory_active else None
    )
    try:
        async for chunk, _metadata in request_agent.astream(
            {"messages": [message]},
            config={"configurable": {"thread_id": scoped_thread_id(context_id, thread_id)}},
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
    finally:
        _memory_context.reset(token)


def clear_messages(context_id: str, thread_id: str) -> None:
    """清空指定用户的持久化会话。"""
    logger.info("清空历史消息，context_id: %s, thread_id: %s", context_id, thread_id)
    storage_thread_id = scoped_thread_id(context_id, thread_id)
    delete_thread = getattr(checkpointer, "delete_thread", None)
    if callable(delete_thread):
        delete_thread(storage_thread_id)
        return

    cursor = connection.cursor()
    for table in ("writes", "checkpoints"):
        try:
            cursor.execute(f"DELETE FROM {table} WHERE thread_id = ?", (storage_thread_id,))
        except sqlite3.Error:
            continue
    connection.commit()


def _get_checkpoint(context_id: str, thread_id: str) -> Any:
    """兼容不同版本 SqliteSaver 的 checkpoint 读取结果。"""
    result = checkpointer.get(
        {"configurable": {"thread_id": scoped_thread_id(context_id, thread_id)}}
    )
    if hasattr(result, "checkpoint"):
        return result.checkpoint
    return result


def get_messages(context_id: str, thread_id: str) -> list[dict[str, str | None]]:
    """获取当前用户指定会话的历史消息。"""
    logger.info("获取历史消息，context_id: %s, thread_id: %s", context_id, thread_id)
    checkpoint = _get_checkpoint(context_id, thread_id)
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
