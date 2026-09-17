"""长期口味记忆、授权和用户数据权利接口。"""
from fastapi import APIRouter, HTTPException, Query

from app.memory.store import (
    CATEGORY_LABELS,
    CONSENT_VERSION,
    MemoryConsentError,
    memory_store,
)
from app.models.schemas import (
    CONTEXT_ID_PATTERN,
    MemoryConsentRequest,
    MemoryDeleteResponse,
    MemoryExportResponse,
    MemoryPolicyResponse,
    MemoryPreference,
    MemoryPreferenceCreate,
    MemoryProfileResponse,
)

router = APIRouter(prefix="/memory", tags=["memory"])

CONTEXT_ID_QUERY = Query(
    min_length=8,
    max_length=128,
    pattern=CONTEXT_ID_PATTERN,
    description="匿名 context_id，不使用姓名、邮箱或手机号",
)


def _handle_value_error(error: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(error))


@router.get("/policy", response_model=MemoryPolicyResponse)
async def memory_policy() -> MemoryPolicyResponse:
    """返回当前长期记忆政策和同意版本。"""
    return MemoryPolicyResponse(
        consent_version=CONSENT_VERSION,
        purpose="仅用于根据用户明确提供的饮食口味偏好定制化推荐菜谱。",
        allowed_categories=CATEGORY_LABELS,
        retention="保存至用户主动删除；用户可随时导出、关闭或清除。",
        user_rights=["查看", "修改", "导出", "逐条删除", "彻底删除", "撤回同意"],
    )


@router.get("/profile", response_model=MemoryProfileResponse)
async def get_memory_profile(context_id: str = CONTEXT_ID_QUERY) -> MemoryProfileResponse:
    """查看长期记忆同意状态和偏好列表。"""
    try:
        return MemoryProfileResponse(**memory_store.get_profile(context_id))
    except ValueError as error:
        raise _handle_value_error(error) from error


@router.put("/consent", response_model=MemoryProfileResponse)
async def update_memory_consent(request: MemoryConsentRequest) -> MemoryProfileResponse:
    """开启或撤回长期记忆同意。"""
    try:
        memory_store.set_consent(
            request.context_id,
            enabled=request.enabled,
            consent_version=request.consent_version,
        )
        return MemoryProfileResponse(**memory_store.get_profile(request.context_id))
    except ValueError as error:
        raise _handle_value_error(error) from error


@router.post("/preferences", response_model=MemoryPreference)
async def add_memory_preference(request: MemoryPreferenceCreate) -> MemoryPreference:
    """在明确同意后新增一条口味偏好。"""
    try:
        return MemoryPreference(
            **memory_store.add_preference(
                request.context_id,
                request.category,
                request.value,
                source="user_explicit",
            )
        )
    except MemoryConsentError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise _handle_value_error(error) from error


@router.delete("/preferences/{preference_id}", response_model=MemoryDeleteResponse)
async def delete_memory_preference(
    preference_id: int,
    context_id: str = CONTEXT_ID_QUERY,
) -> MemoryDeleteResponse:
    """删除一条指定偏好。"""
    try:
        deleted = memory_store.delete_preference(context_id, preference_id)
    except ValueError as error:
        raise _handle_value_error(error) from error
    if not deleted:
        raise HTTPException(status_code=404, detail="偏好不存在或不属于当前 context_id。")
    return MemoryDeleteResponse(success=True, deleted_preferences=1)


@router.get("/export", response_model=MemoryExportResponse)
async def export_memory_profile(
    context_id: str = CONTEXT_ID_QUERY,
) -> MemoryExportResponse:
    """导出用户长期记忆 JSON。"""
    try:
        return MemoryExportResponse(**memory_store.export_profile(context_id))
    except ValueError as error:
        raise _handle_value_error(error) from error


@router.delete("/profile", response_model=MemoryDeleteResponse)
async def delete_memory_profile(context_id: str = CONTEXT_ID_QUERY) -> MemoryDeleteResponse:
    """彻底删除当前 context_id 的同意记录和全部偏好。"""
    try:
        result = memory_store.delete_profile(context_id)
    except ValueError as error:
        raise _handle_value_error(error) from error
    return MemoryDeleteResponse(success=True, **result)
