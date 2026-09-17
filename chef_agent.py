"""AI 私厨命令行入口（兼容旧版启动方式）。"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

from app.agents.personal_chief import runtime_status, search_recipes


def _configure_console() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


async def main() -> None:
    _configure_console()
    thread_id = os.getenv("CHEF_THREAD_ID") or uuid.uuid4().hex
    status = runtime_status()

    print("欢迎使用 AI 私厨管家")
    print(f"会话 ID：{thread_id}")
    print(f"当前模型：{status['model']}")
    if not status["dashscope_configured"]:
        print("提示：DASHSCOPE_API_KEY 尚未配置，请先修改 .env。")
    print("输入食材照片 URL 或食材清单，输入 q 退出。\n")

    while True:
        try:
            user_input = input("你：").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n再见。")
            return

        if user_input.lower() in {"q", "quit", "exit"}:
            print("再见。")
            return
        if not user_input:
            continue

        print("\n小厨：", end="", flush=True)
        async for chunk in search_recipes(user_input, None, thread_id):
            print(chunk, end="", flush=True)
        print("\n")


if __name__ == "__main__":
    asyncio.run(main())