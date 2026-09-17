"""统一日志配置。"""
import logging
import sys


def setup_logging() -> None:
    """初始化项目日志，重复调用时不会重复添加 handler。"""
    root = logging.getLogger()
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)


logger = logging.getLogger("personal_chief")