"""LLM API"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.models.common import Response
from app.models.llm import (
    LLMCreate,
    LLMUpdate,
    LLMResponse,
    LLMTestResponse
)
from app.services.llm_service import LLMService


router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


@router.post("")
async def create_llm(
    request: LLMCreate,
    session: AsyncSession = Depends(get_db)
) -> Response[LLMResponse]:
    """创建 LLM 模型"""
    service = LLMService(session)
    model = await service.create_llm(request)
    return Response[LLMResponse](
        data=LLMResponse.model_validate(model)
    )


@router.get("")
async def list_llms(
    keyword: Optional[str] = None,
    session: AsyncSession = Depends(get_db)
) -> Response[List[LLMResponse]]:
    """列出 LLM 模型，支持搜索"""
    service = LLMService(session)
    models = await service.list_llms(keyword)
    return Response[List[LLMResponse]](
        data=[LLMResponse.model_validate(m) for m in models]
    )


@router.get("/{model_id}")
async def get_llm(
    model_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[LLMResponse]:
    """获取 LLM 模型详情"""
    service = LLMService(session)
    model = await service.get_llm(model_id)
    if not model:
        return Response(code=404, message="LLM model not found", data=None)
    return Response[LLMResponse](
        data=LLMResponse.model_validate(model)
    )


@router.put("/{model_id}")
async def update_llm(
    model_id: UUID,
    request: LLMUpdate,
    session: AsyncSession = Depends(get_db)
) -> Response[LLMResponse]:
    """更新 LLM 模型"""
    service = LLMService(session)
    model = await service.update_llm(model_id, request)
    if not model:
        return Response(code=404, message="LLM model not found", data=None)
    return Response[LLMResponse](
        data=LLMResponse.model_validate(model)
    )


@router.delete("/{model_id}")
async def delete_llm(
    model_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[None]:
    """删除 LLM 模型"""
    service = LLMService(session)
    success, message = await service.delete_llm(model_id)
    if not success:
        return Response(code=1, message=message, data=None)
    return Response[None](code=0, message="Deleted", data=None)


@router.post("/{model_id}/test")
async def test_connection(
    model_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[LLMTestResponse]:
    """测试 LLM 连接"""
    service = LLMService(session)
    success, message = await service.test_connection(model_id)
    return Response[LLMTestResponse](
        data=LLMTestResponse(success=success, message=message)
    )
