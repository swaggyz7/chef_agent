"""基于 SQLite 的可选长期口味记忆存储。

隐私设计：
1. 默认关闭，必须记录明确同意后才能读写。
2. 只保存固定类别的饮食口味，不保存姓名、电话、邮箱、健康或宗教等敏感属性。
3. 支持用户查看、导出、逐条删除和彻底删除。
"""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEMORY_DB_PATH = (os.getenv("MEMORY_DB_PATH") or "").strip()
DEFAULT_DB_PATH = (
    Path(MEMORY_DB_PATH)
    if MEMORY_DB_PATH
    else PROJECT_ROOT / "db" / "user_memory.db"
)

CONSENT_VERSION = "2026-09-17-v1"

CATEGORY_LABELS = {
    "spicy_level": "辣度",
    "flavor": "口味",
    "cuisine": "菜系",
    "liked_ingredient": "偏好食材",
    "disliked_ingredient": "不喜欢/避免的食材",
    "dietary_style": "饮食风格",
    "cooking_style": "烹饪方式",
    "meal_preference": "餐食偏好",
}

SOURCE_LABELS = {
    "user_explicit": "用户主动填写",
    "agent_explicit": "用户在对话中明确要求记住",
}

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_CONTEXT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_MAX_PREFERENCE_LENGTH = 60
_MAX_PREFERENCES = 100


class MemoryConsentError(PermissionError):
    """没有有效同意时拒绝访问长期记忆。"""


class MemoryStore:
    """长期偏好的 SQLite 存储。"""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_consents (
                    context_id TEXT PRIMARY KEY,
                    memory_enabled INTEGER NOT NULL DEFAULT 0,
                    consent_version TEXT,
                    consented_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS taste_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    context_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user_explicit',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(context_id, category, value),
                    FOREIGN KEY(context_id)
                        REFERENCES memory_consents(context_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_taste_preferences_context
                    ON taste_preferences(context_id);
                """
            )

    @staticmethod
    def validate_context_id(context_id: str) -> str:
        value = (context_id or "").strip()
        if not _CONTEXT_ID_PATTERN.fullmatch(value):
            raise ValueError("context_id 必须是 8-128 位字母、数字、下划线或连字符。")
        return value

    @staticmethod
    def validate_category(category: str) -> str:
        value = (category or "").strip()
        if value not in CATEGORY_LABELS:
            raise ValueError(f"不支持的偏好类别：{value or '空值'}")
        return value

    @staticmethod
    def validate_value(value: str) -> str:
        cleaned = _CONTROL_CHARS.sub(" ", (value or "").strip())
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            raise ValueError("偏好内容不能为空。")
        if len(cleaned) > _MAX_PREFERENCE_LENGTH:
            raise ValueError(f"偏好内容不能超过 {_MAX_PREFERENCE_LENGTH} 个字符。")
        return cleaned

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def set_consent(
        self,
        context_id: str,
        enabled: bool,
        consent_version: str,
    ) -> dict[str, Any]:
        """开启或关闭长期记忆同意状态。"""
        context_id = self.validate_context_id(context_id)
        if enabled and consent_version != CONSENT_VERSION:
            raise ValueError("隐私同意版本不匹配，请刷新页面后重新确认。")

        now = self._now()
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT consented_at FROM memory_consents WHERE context_id = ?",
                (context_id,),
            ).fetchone()
            consented_at = existing["consented_at"] if existing else None
            if enabled and not consented_at:
                consented_at = now

            connection.execute(
                """
                INSERT INTO memory_consents (
                    context_id, memory_enabled, consent_version,
                    consented_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(context_id) DO UPDATE SET
                    memory_enabled = excluded.memory_enabled,
                    consent_version = excluded.consent_version,
                    consented_at = COALESCE(excluded.consented_at, memory_consents.consented_at),
                    updated_at = excluded.updated_at
                """,
                (
                    context_id,
                    1 if enabled else 0,
                    consent_version if enabled else None,
                    consented_at,
                    now,
                ),
            )
        return self.get_consent(context_id)

    def get_consent(self, context_id: str) -> dict[str, Any]:
        """读取同意状态；没有记录时返回默认关闭。"""
        context_id = self.validate_context_id(context_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM memory_consents WHERE context_id = ?",
                (context_id,),
            ).fetchone()
        if not row:
            return {
                "context_id": context_id,
                "memory_enabled": False,
                "consent_version": None,
                "consented_at": None,
                "updated_at": None,
            }
        return {
            "context_id": row["context_id"],
            "memory_enabled": bool(row["memory_enabled"]),
            "consent_version": row["consent_version"],
            "consented_at": row["consented_at"],
            "updated_at": row["updated_at"],
        }

    def has_active_consent(self, context_id: str, consent_version: str = CONSENT_VERSION) -> bool:
        """判断当前 context 是否有可用的明确同意。"""
        try:
            consent = self.get_consent(context_id)
        except ValueError:
            return False
        return bool(
            consent["memory_enabled"]
            and consent["consent_version"] == consent_version
        )

    def add_preference(
        self,
        context_id: str,
        category: str,
        value: str,
        source: str = "user_explicit",
    ) -> dict[str, Any]:
        """在有效同意下保存一条口味偏好。"""
        context_id = self.validate_context_id(context_id)
        category = self.validate_category(category)
        value = self.validate_value(value)
        if source not in SOURCE_LABELS:
            raise ValueError("不支持的偏好来源。")
        if not self.has_active_consent(context_id):
            raise MemoryConsentError("尚未开启长期记忆或同意版本已失效。")

        now = self._now()
        with self._connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS total FROM taste_preferences WHERE context_id = ?",
                (context_id,),
            ).fetchone()["total"]
            if count >= _MAX_PREFERENCES:
                raise ValueError(f"最多保存 {_MAX_PREFERENCES} 条口味偏好。")

            connection.execute(
                """
                INSERT INTO taste_preferences (
                    context_id, category, value, source, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(context_id, category, value) DO UPDATE SET
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (context_id, category, value, source, now, now),
            )
            row = connection.execute(
                """
                SELECT * FROM taste_preferences
                WHERE context_id = ? AND category = ? AND value = ?
                """,
                (context_id, category, value),
            ).fetchone()
        return self._preference_row(row)

    def list_preferences(self, context_id: str, require_consent: bool = True) -> list[dict[str, Any]]:
        """列出已保存偏好。"""
        context_id = self.validate_context_id(context_id)
        if require_consent and not self.has_active_consent(context_id):
            return []
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM taste_preferences
                WHERE context_id = ?
                ORDER BY category, created_at, id
                """,
                (context_id,),
            ).fetchall()
        return [self._preference_row(row) for row in rows]

    def delete_preference(self, context_id: str, preference_id: int) -> bool:
        """删除指定偏好。"""
        context_id = self.validate_context_id(context_id)
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM taste_preferences WHERE id = ? AND context_id = ?",
                (preference_id, context_id),
            )
        return cursor.rowcount > 0

    def delete_profile(self, context_id: str) -> dict[str, int]:
        """彻底删除同意记录和全部偏好。"""
        context_id = self.validate_context_id(context_id)
        with self._connection() as connection:
            preference_cursor = connection.execute(
                "DELETE FROM taste_preferences WHERE context_id = ?",
                (context_id,),
            )
            consent_cursor = connection.execute(
                "DELETE FROM memory_consents WHERE context_id = ?",
                (context_id,),
            )
        return {
            "deleted_preferences": preference_cursor.rowcount,
            "deleted_consents": consent_cursor.rowcount,
        }

    def get_profile(self, context_id: str) -> dict[str, Any]:
        """返回同意状态和所有偏好，用于查看或导出。"""
        consent = self.get_consent(context_id)
        preferences = self.list_preferences(context_id, require_consent=False)
        return {
            **consent,
            "preferences": preferences,
            "preference_count": len(preferences),
        }

    def export_profile(self, context_id: str) -> dict[str, Any]:
        """导出用户可携带的数据副本。"""
        return {
            "exported_at": self._now(),
            "format_version": "1.0",
            "consent_version": CONSENT_VERSION,
            "profile": self.get_profile(context_id),
        }

    def build_prompt_context(self, context_id: str) -> str:
        """把已确认偏好转换成 Agent 的用途限定上下文。"""
        if not self.has_active_consent(context_id):
            return ""
        preferences = self.list_preferences(context_id, require_consent=True)
        if not preferences:
            return ""

        lines = [
            "【已授权的长期口味偏好】",
            "以下内容由用户主动提供，仅用于个性化食谱推荐，不得推断或扩展其他个人属性。",
        ]
        for item in preferences:
            lines.append(f"- {item['category_label']}：{item['value']}")
        lines.append("用户本轮的明确要求优先于上述偏好。")
        return "\n".join(lines)

    @staticmethod
    def _preference_row(row: sqlite3.Row) -> dict[str, Any]:
        category = row["category"]
        return {
            "id": row["id"],
            "context_id": row["context_id"],
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, category),
            "value": row["value"],
            "source": row["source"],
            "source_label": SOURCE_LABELS.get(row["source"], row["source"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


memory_store = MemoryStore()
