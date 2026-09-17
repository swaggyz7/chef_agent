"""FastAPI 请求与响应数据模型。"""
from typing import Any, Literal

from pydantic import BaseModel, Field

CONTEXT_ID_PATTERN = r"^[A-Za-z0-9_-]{8,128}$"


class ChatRequest(BaseModel):
    """聊天请求。"""

    message: str = Field(min_length=1, max_length=8000)
    image_url: str | None = Field(default=None, max_length=4000)
    context_id: str = Field(min_length=8, max_length=128, pattern=CONTEXT_ID_PATTERN)
    thread_id: str = Field(default="default", min_length=1, max_length=128)
    use_memory: bool = False


class ChatMessage(BaseModel):
    """会话历史中的单条消息。"""

    role: Literal["user", "assistant"]
    content: str
    image_url: str | None = None


class ChatHistoryResponse(BaseModel):
    """会话历史响应。"""

    messages: list[ChatMessage]


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


class MemoryPolicyResponse(BaseModel):
    """长期记忆隐私政策摘要。"""

    consent_version: str
    default_enabled: bool = False
    purpose: str
    allowed_categories: dict[str, str]
    retention: str
    user_rights: list[str]


class MemoryConsentRequest(BaseModel):
    """开启或关闭长期记忆。"""

    context_id: str = Field(min_length=8, max_length=128, pattern=CONTEXT_ID_PATTERN)
    enabled: bool
    consent_version: str


class MemoryPreferenceCreate(BaseModel):
    """用户主动添加一条口味偏好。"""

    context_id: str = Field(min_length=8, max_length=128, pattern=CONTEXT_ID_PATTERN)
    category: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=60)


class MemoryPreference(BaseModel):
    """长期口味偏好。"""

    id: int
    context_id: str
    category: str
    category_label: str
    value: str
    source: str
    source_label: str
    created_at: str
    updated_at: str


class MemoryProfileResponse(BaseModel):
    """长期记忆配置和偏好列表。"""

    context_id: str
    memory_enabled: bool
    consent_version: str | None = None
    consented_at: str | None = None
    updated_at: str | None = None
    preferences: list[MemoryPreference] = Field(default_factory=list)
    preference_count: int = 0


class MemoryExportResponse(BaseModel):
    """用户数据导出。"""

    exported_at: str
    format_version: str
    consent_version: str
    profile: dict[str, Any]


class MemoryDeleteResponse(BaseModel):
    """长期记忆删除结果。"""

    success: bool = True
    deleted_preferences: int = 0
    deleted_consents: int = 0

class KnowledgeStatsResponse(BaseModel):
    """本地菜品图谱统计。"""

    dish_count: int
    edge_count: int
    vector_count: int
    dimensions: int
    embedding_type: str
    database: str


class DishNode(BaseModel):
    """菜品图谱节点。"""

    id: int
    name: str
    cuisine: str
    category: str
    summary: str
    ingredients: list[str] = Field(default_factory=list)
    flavors: list[str] = Field(default_factory=list)
    cooking_methods: list[str] = Field(default_factory=list)
    dietary_tags: list[str] = Field(default_factory=list)
    difficulty: str
    source: str


class DishEdge(BaseModel):
    """菜品与图谱属性之间的关系边。"""

    relation: str
    target_type: str
    target_value: str
    weight: float


class RelatedDish(BaseModel):
    """通过共享图谱关系得到的相关菜品。"""

    id: int
    name: str
    cuisine: str
    shared_edges: int
    weight: float


class DishGraphResponse(DishNode):
    """完整菜品图谱节点。"""

    edges: list[DishEdge] = Field(default_factory=list)
    related_dishes: list[RelatedDish] = Field(default_factory=list)


class KnowledgeSearchHit(DishNode):
    """本地向量召回结果。"""

    score: float
    edges: list[DishEdge] = Field(default_factory=list)
    related_dishes: list[RelatedDish] = Field(default_factory=list)


class KnowledgeSearchResponse(BaseModel):
    """本地图谱检索响应。"""

    query: str
    top_k: int
    results: list[KnowledgeSearchHit] = Field(default_factory=list)
