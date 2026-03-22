"""Execution API"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.models.common import Response, ListResponse
from app.models.execution import (
    CreateExecutionRequest,
    ExecutionResponse,
    ExecutionTraceResponse,
    SpanResponse
)
from app.services.execution_service import ExecutionService
from app.services.trace_fetcher import TraceFetcherImpl


router = APIRouter(prefix="/api/v1/execution", tags=["execution"])


@router.post("")
async def create_execution(
    request: CreateExecutionRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db)
) -> Response[UUID]:
    """触发执行测试"""
    try:
        service = ExecutionService(session)
        execution_id = await service.create_execution(request, background_tasks)
        return Response[UUID](data=execution_id)
    except ValueError as e:
        return Response(code=1, message=str(e), data=None)


@router.get("")
async def list_executions(
    agent_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_db)
) -> Response[ListResponse[ExecutionResponse]]:
    """列出执行记录"""
    service = ExecutionService(session)
    total, executions = await service.list_executions(agent_id, scenario_id, limit, offset)
    return Response[ListResponse[ExecutionResponse]](
        data=ListResponse[ExecutionResponse](
            total=total,
            items=[ExecutionResponse.model_validate(e) for e in executions]
        )
    )


@router.get("/{execution_id}")
async def get_execution(
    execution_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[ExecutionResponse]:
    """获取执行详情"""
    service = ExecutionService(session)
    execution = await service.get_execution(execution_id)
    if not execution:
        return Response(code=404, message="Execution not found", data=None)
    return Response[ExecutionResponse](
        data=ExecutionResponse.model_validate(execution)
    )


@router.get("/{execution_id}/trace")
async def get_trace(
    execution_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[ExecutionTraceResponse]:
    """获取 Trace 用于回放"""
    service = ExecutionService(session)
    execution = await service.get_execution(execution_id)
    if not execution:
        return Response(code=404, message="Execution not found", data=None)

    fetcher = TraceFetcherImpl(session)
    spans = await fetcher.fetch_spans(execution.trace_id)

    span_responses = []
    for span in spans:
        span_responses.append(SpanResponse(
            span_id=span.span_id,
            span_type=span.span_type,
            name=span.name,
            input=span.input,
            output=span.output,
            duration_ms=span.duration_ms,
            ttft_ms=span.metrics.ttft_ms,
            tpot_ms=span.metrics.tpot_ms
        ))

    return Response[ExecutionTraceResponse](
        data=ExecutionTraceResponse(
            trace_id=execution.trace_id,
            spans=span_responses
        )
    )


@router.delete("/{execution_id}")
async def delete_execution(
    execution_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[None]:
    """删除执行记录"""
    service = ExecutionService(session)
    success = await service.delete_execution(execution_id)
    if not success:
        return Response(code=404, message="Execution not found", data=None)
    return Response[None](code=0, message="Deleted", data=None)
