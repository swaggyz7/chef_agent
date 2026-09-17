"""本地菜品图谱与知识库检索接口。"""
from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    DishGraphResponse,
    DishNode,
    KnowledgeSearchResponse,
    KnowledgeStatsResponse,
)
from app.rag.local_dish_graph import dish_graph

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/stats", response_model=KnowledgeStatsResponse)
async def knowledge_stats() -> KnowledgeStatsResponse:
    """查看本地菜品图谱规模。"""
    return KnowledgeStatsResponse(**dish_graph.stats())


@router.get("/dishes", response_model=list[DishNode])
async def list_dishes() -> list[DishNode]:
    """列出本地菜品图谱中的菜品。"""
    return [DishNode(**dish) for dish in dish_graph.list_dishes()]


@router.get("/dishes/{dish_id}", response_model=DishGraphResponse)
async def get_dish(dish_id: int) -> DishGraphResponse:
    """按 ID 查询菜品节点、关系边和相关菜品。"""
    try:
        return DishGraphResponse(**dish_graph.get_dish(dish_id))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    q: str = Query(min_length=1, max_length=300),
    top_k: int = Query(default=5, ge=1, le=10),
) -> KnowledgeSearchResponse:
    """使用本地 SQLite 向量和图谱关系检索菜品。"""
    results = dish_graph.search(q, top_k=top_k)
    return KnowledgeSearchResponse(query=q, top_k=top_k, results=results)