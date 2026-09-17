"""基于 SQLite 的本地菜品图谱与轻量向量检索。

菜品节点、关系边和 float32 向量全部保存在 SQLite。
向量由字符 n-gram 哈希生成，不需要外部 Embedding API。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from array import array
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "dish_knowledge.db"
VECTOR_DIMENSIONS = 384

DEMO_DISHES = [
    {"name": "番茄炒蛋", "cuisine": "家常菜", "category": "快手菜", "summary": "酸甜开胃、制作快速。", "ingredients": ["西红柿", "鸡蛋", "葱"], "flavors": ["酸甜", "咸鲜"], "cooking_methods": ["炒"], "dietary_tags": ["快手", "家常"], "difficulty": "简单"},
    {"name": "西兰花炒鸡胸肉", "cuisine": "轻食", "category": "高蛋白菜", "summary": "高蛋白、低脂、口感清爽，适合健身饮食。", "ingredients": ["西兰花", "鸡胸肉", "大蒜"], "flavors": ["清淡", "咸鲜"], "cooking_methods": ["炒"], "dietary_tags": ["高蛋白", "低脂", "健身"], "difficulty": "简单"},
    {"name": "香菇滑鸡", "cuisine": "粤菜", "category": "荤菜", "summary": "鸡肉嫩滑、菌菇鲜香，适合搭配米饭。", "ingredients": ["鸡肉", "香菇", "姜"], "flavors": ["鲜香", "咸鲜"], "cooking_methods": ["炒", "焖"], "dietary_tags": ["下饭", "菌菇"], "difficulty": "中等"},
    {"name": "麻婆豆腐", "cuisine": "川菜", "category": "下饭菜", "summary": "麻辣鲜香、豆腐软嫩。", "ingredients": ["豆腐", "牛肉末", "豆瓣酱", "花椒"], "flavors": ["麻辣", "鲜香"], "cooking_methods": ["烧", "炒"], "dietary_tags": ["下饭", "重口味"], "difficulty": "中等"},
    {"name": "清蒸鲈鱼", "cuisine": "粤菜", "category": "海鲜", "summary": "突出鱼肉本味，清淡鲜嫩。", "ingredients": ["鲈鱼", "姜", "葱"], "flavors": ["清淡", "鲜香"], "cooking_methods": ["蒸"], "dietary_tags": ["高蛋白", "低脂"], "difficulty": "中等"},
    {"name": "蒜蓉西兰花", "cuisine": "家常菜", "category": "素菜", "summary": "蒜香清爽，保留蔬菜脆嫩口感。", "ingredients": ["西兰花", "大蒜"], "flavors": ["蒜香", "清淡"], "cooking_methods": ["炒", "焯"], "dietary_tags": ["素食", "低脂", "快手"], "difficulty": "简单"},
    {"name": "土豆炖牛肉", "cuisine": "家常菜", "category": "炖菜", "summary": "汤汁浓郁、饱腹感强。", "ingredients": ["土豆", "牛肉", "胡萝卜", "洋葱"], "flavors": ["咸香", "浓郁"], "cooking_methods": ["炖"], "dietary_tags": ["高蛋白", "饱腹"], "difficulty": "中等"},
    {"name": "三文鱼蔬菜烤盘", "cuisine": "西式", "category": "烤箱菜", "summary": "三文鱼搭配多种蔬菜，营养均衡。", "ingredients": ["三文鱼", "西兰花", "彩椒", "胡萝卜", "蘑菇"], "flavors": ["鲜香", "清淡"], "cooking_methods": ["烤"], "dietary_tags": ["高蛋白", "低碳水", "一锅出"], "difficulty": "简单"},
]

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]")
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_list(values: Iterable[str]) -> str:
    return json.dumps([str(item).strip() for item in values if str(item).strip()], ensure_ascii=False)


def _load_list(value: str) -> list[str]:
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def _tokenize(text: str) -> list[str]:
    normalized = (text or "").lower()
    tokens = [item for item in _TOKEN_PATTERN.findall(normalized) if item]
    cjk = _CJK_PATTERN.findall(normalized)
    tokens.extend(cjk)
    tokens.extend("".join(cjk[index:index + 2]) for index in range(len(cjk) - 1))
    return tokens


def _hash_index(token: str) -> tuple[int, float]:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest[:4], "little") % VECTOR_DIMENSIONS, 1.0 if digest[4] % 2 == 0 else -1.0


def embed_text(text: str) -> list[float]:
    vector = [0.0] * VECTOR_DIMENSIONS
    counts: dict[str, int] = {}
    for token in _tokenize(text):
        counts[token] = counts.get(token, 0) + 1
    for token, count in counts.items():
        index, sign = _hash_index(token)
        vector[index] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def _pack_vector(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def _unpack_vector(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return list(values)


class LocalDishGraph:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._seed()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS dish_nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    cuisine TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    ingredients TEXT NOT NULL DEFAULT '[]',
                    flavors TEXT NOT NULL DEFAULT '[]',
                    cooking_methods TEXT NOT NULL DEFAULT '[]',
                    dietary_tags TEXT NOT NULL DEFAULT '[]',
                    difficulty TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'demo',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dish_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dish_id INTEGER NOT NULL,
                    relation TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_value TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    UNIQUE(dish_id, relation, target_value),
                    FOREIGN KEY(dish_id) REFERENCES dish_nodes(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS dish_vectors (
                    dish_id INTEGER PRIMARY KEY,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(dish_id) REFERENCES dish_nodes(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_dish_edges_target
                    ON dish_edges(target_type, target_value);
            ''')

    def _seed(self) -> None:
        with self._connection() as connection:
            count = connection.execute("SELECT COUNT(*) AS total FROM dish_nodes").fetchone()["total"]
        if not count:
            for dish in DEMO_DISHES:
                self.add_dish(dish, source="demo")

    def add_dish(self, dish: dict[str, Any], source: str = "user") -> dict[str, Any]:
        name = str(dish.get("name", "")).strip()
        if not name:
            raise ValueError("菜品名称不能为空。")
        now = _now()
        fields = {
            "ingredients": _json_list(dish.get("ingredients", [])),
            "flavors": _json_list(dish.get("flavors", [])),
            "cooking_methods": _json_list(dish.get("cooking_methods", [])),
            "dietary_tags": _json_list(dish.get("dietary_tags", [])),
        }
        with self._connection() as connection:
            connection.execute('''
                INSERT INTO dish_nodes (
                    name, cuisine, category, summary, ingredients, flavors,
                    cooking_methods, dietary_tags, difficulty, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    cuisine=excluded.cuisine, category=excluded.category,
                    summary=excluded.summary, ingredients=excluded.ingredients,
                    flavors=excluded.flavors, cooking_methods=excluded.cooking_methods,
                    dietary_tags=excluded.dietary_tags, difficulty=excluded.difficulty,
                    source=excluded.source, updated_at=excluded.updated_at
            ''', (
                name, str(dish.get("cuisine", "")).strip(), str(dish.get("category", "")).strip(),
                str(dish.get("summary", "")).strip(), fields["ingredients"], fields["flavors"],
                fields["cooking_methods"], fields["dietary_tags"], str(dish.get("difficulty", "")).strip(),
                source, now, now,
            ))
            row = connection.execute("SELECT * FROM dish_nodes WHERE name = ?", (name,)).fetchone()
            dish_id = int(row["id"])
            connection.execute("DELETE FROM dish_edges WHERE dish_id = ?", (dish_id,))
            edge_groups = [
                ("HAS_INGREDIENT", "ingredient", _load_list(fields["ingredients"]), 1.0),
                ("HAS_FLAVOR", "flavor", _load_list(fields["flavors"]), 0.9),
                ("USES_METHOD", "cooking_method", _load_list(fields["cooking_methods"]), 0.8),
                ("HAS_DIETARY_TAG", "dietary_tag", _load_list(fields["dietary_tags"]), 0.7),
            ]
            for relation, target_type, values, weight in edge_groups:
                for value in values:
                    connection.execute('''
                        INSERT OR IGNORE INTO dish_edges
                        (dish_id, relation, target_type, target_value, weight)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (dish_id, relation, target_type, value, weight))
            vector = embed_text(self._dish_text(row))
            connection.execute('''
                INSERT INTO dish_vectors (dish_id, dimensions, vector, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(dish_id) DO UPDATE SET
                    dimensions=excluded.dimensions, vector=excluded.vector, updated_at=excluded.updated_at
            ''', (dish_id, VECTOR_DIMENSIONS, _pack_vector(vector), now))
        return self.get_dish(dish_id)

    @staticmethod
    def _row_to_dish(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "cuisine": row["cuisine"],
            "category": row["category"],
            "summary": row["summary"],
            "ingredients": _load_list(row["ingredients"]),
            "flavors": _load_list(row["flavors"]),
            "cooking_methods": _load_list(row["cooking_methods"]),
            "dietary_tags": _load_list(row["dietary_tags"]),
            "difficulty": row["difficulty"],
            "source": row["source"],
        }

    @staticmethod
    def _dish_text(row: sqlite3.Row) -> str:
        parts = [row["name"], row["cuisine"], row["category"], row["summary"]]
        for field in ("ingredients", "flavors", "cooking_methods", "dietary_tags"):
            parts.extend(_load_list(row[field]))
        parts.append(row["difficulty"])
        return " ".join(parts)

    def list_dishes(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM dish_nodes ORDER BY id").fetchall()
        return [self._row_to_dish(row) for row in rows]

    def get_dish(self, dish_id: int) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM dish_nodes WHERE id = ?", (dish_id,)).fetchone()
            if not row:
                raise ValueError(f"菜品不存在：{dish_id}")
            edges = connection.execute('''
                SELECT relation, target_type, target_value, weight
                FROM dish_edges WHERE dish_id = ? ORDER BY relation, target_value
            ''', (dish_id,)).fetchall()
            related = connection.execute('''
                SELECT other.id, other.name, other.cuisine,
                       COUNT(*) AS shared_edges,
                       ROUND(SUM(edge.weight * other_edge.weight), 3) AS weight
                FROM dish_edges edge
                JOIN dish_edges other_edge
                  ON other_edge.target_type = edge.target_type
                 AND other_edge.target_value = edge.target_value
                 AND other_edge.dish_id != edge.dish_id
                JOIN dish_nodes other ON other.id = other_edge.dish_id
                WHERE edge.dish_id = ?
                GROUP BY other.id, other.name, other.cuisine
                ORDER BY weight DESC, shared_edges DESC, other.id LIMIT 5
            ''', (dish_id,)).fetchall()
        result = self._row_to_dish(row)
        result["edges"] = [dict(item) for item in edges]
        result["related_dishes"] = [dict(item) for item in related]
        return result

    def get_dish_by_name(self, name: str) -> dict[str, Any]:
        value = (name or "").strip()
        if not value:
            raise ValueError("菜品名称不能为空。")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id FROM dish_nodes WHERE name = ? OR name LIKE ? ORDER BY id LIMIT 1",
                (value, f"%{value}%"),
            ).fetchone()
        if not row:
            raise ValueError(f"未找到菜品：{value}")
        return self.get_dish(int(row["id"]))

    def _lexical_score(self, query: str, row: sqlite3.Row) -> float:
        query_terms = set(_tokenize(query))
        dish_terms = set(_tokenize(self._dish_text(row)))
        union = len(query_terms | dish_terms) or 1
        jaccard = len(query_terms & dish_terms) / union
        return min(1.0, jaccard * 2.0)

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        value = (query or "").strip()
        if not value:
            return []
        limit = max(1, min(int(top_k), 10))
        query_vector = embed_text(value)
        with self._connection() as connection:
            rows = connection.execute('''
                SELECT node.*, vector.vector FROM dish_nodes node
                JOIN dish_vectors vector ON vector.dish_id = node.id
            ''').fetchall()
        ranked = []
        for row in rows:
            vector_score = sum(a * b for a, b in zip(query_vector, _unpack_vector(row["vector"])))
            vector_score = (max(-1.0, min(1.0, vector_score)) + 1.0) / 2.0
            score = round(vector_score * 0.72 + self._lexical_score(value, row) * 0.28, 4)
            ranked.append((score, row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        results = []
        for score, row in ranked[:limit]:
            dish = self.get_dish(int(row["id"]))
            dish["score"] = score
            dish["related_dishes"] = dish["related_dishes"][:3]
            results.append(dish)
        return results

    def stats(self) -> dict[str, Any]:
        with self._connection() as connection:
            dish_count = connection.execute("SELECT COUNT(*) AS total FROM dish_nodes").fetchone()["total"]
            edge_count = connection.execute("SELECT COUNT(*) AS total FROM dish_edges").fetchone()["total"]
            vector_count = connection.execute("SELECT COUNT(*) AS total FROM dish_vectors").fetchone()["total"]
        return {
            "dish_count": int(dish_count),
            "edge_count": int(edge_count),
            "vector_count": int(vector_count),
            "dimensions": VECTOR_DIMENSIONS,
            "embedding_type": "sqlite_hash_char_ngram",
            "database": str(self.db_path),
        }


dish_graph = LocalDishGraph()