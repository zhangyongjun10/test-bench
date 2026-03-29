"""Execution API"""

import json
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.core.logger import logger
from app.models.common import Response, ListResponse
from app.models.execution import (
    CreateExecutionRequest,
    ExecutionResponse,
    ExecutionTraceResponse,
    SpanResponse
)
from app.models.comparison import DetailedComparisonResponse, RecompareResponse
from app.domain.entities.comparison import ComparisonStatus
from app.domain.entities.execution import ExecutionStatus
from app.domain.repositories.execution_repo import SQLAlchemyExecutionRepository
from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository
from app.domain.repositories.scenario_repo import SQLAlchemyScenarioRepository
from app.services.execution_service import ExecutionService
from app.services.comparison import ComparisonService
from app.services.trace_fetcher import TraceFetcherImpl
from app.services.llm_service import LLMService


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


@router.get("/{execution_id}/comparison")
async def get_comparison(
    execution_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[DetailedComparisonResponse]:
    """获取详细比对结果"""
    comparison_repo = SQLAlchemyComparisonRepository()
    comparison = await comparison_repo.get_by_execution_id(session, execution_id)
    if not comparison:
        return Response(code=404, message="Comparison not found", data=None)

    # 解析 details_json，处理解析失败
    details: Dict[str, Any] = {
        'tool_comparisons': [],
        'llm_comparison': None
    }
    if comparison.details_json:
        try:
            details = json.loads(comparison.details_json)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse details_json for comparison {execution_id}: {e}")
            # 解析失败返回空结构，不影响整个API响应

    response = DetailedComparisonResponse(
        id=comparison.id,
        execution_id=comparison.execution_id,
        scenario_id=comparison.scenario_id,
        trace_id=comparison.trace_id,
        process_score=comparison.process_score,
        result_score=comparison.result_score,
        overall_passed=comparison.overall_passed,
        tool_comparisons=details.get('tool_comparisons', []),
        llm_comparison=details.get('llm_comparison'),
        status=comparison.status,
        error_message=comparison.error_message,
        retry_count=comparison.retry_count,
        created_at=comparison.created_at,
        updated_at=comparison.updated_at,
        completed_at=comparison.completed_at,
    )

    return Response[DetailedComparisonResponse](data=response)


async def run_recompare(
    execution_id: UUID,
    session: AsyncSession,
    llm_model_id: Optional[UUID] = None,
) -> None:
    """后台任务：重新执行比对"""
    from app.services.execution_service import ExecutionService
    from app.domain.entities.comparison import ComparisonResult, ComparisonStatus
    from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository
    from app.domain.repositories.scenario_repo import SQLAlchemyScenarioRepository
    from app.services.comparison import ComparisonService
    from app.services.trace_fetcher import TraceFetcherImpl
    from app.services.llm_service import LLMService
    from app.clients.llm_client import DummyLLMClient
    from datetime import datetime

    execution_repo = SQLAlchemyExecutionRepository(session)
    execution = await execution_repo.get_by_id(execution_id)
    if not execution:
        logger.error(f"Execution not found for recompare: {execution_id}")
        return

    scenario_repo = SQLAlchemyScenarioRepository(session)
    scenario = await scenario_repo.get_by_id(execution.scenario_id)
    if not scenario:
        logger.error(f"Scenario not found for recompare: {execution.scenario_id}")
        return

    # 获取 trace spans
    trace_fetcher = TraceFetcherImpl(session)
    spans = await trace_fetcher.fetch_spans(execution.trace_id)

    # 获取 LLM client（如果需要）
    llm_service = LLMService(session)
    llm_client = None
    # 使用传入的 llm_model_id，如果没有则使用 execution 上的
    used_llm_model_id = llm_model_id or execution.llm_model_id
    if used_llm_model_id:
        llm_model = await llm_service.get_llm(used_llm_model_id)
        if llm_model:
            llm_client = llm_service.get_client(llm_model)
        else:
            logger.warning(f"LLM model not found: {used_llm_model_id}, continuing without LLM verification")
            llm_client = DummyLLMClient()
    else:
        logger.warning(f"No llm_model_id for execution: {execution_id}, continuing without LLM verification")
        llm_client = DummyLLMClient()

    # 创建新的比对记录，先设置为 processing
    comparison_repo = SQLAlchemyComparisonRepository()
    comparison = ComparisonResult(
        execution_id=execution.id,
        scenario_id=scenario.id,
        trace_id=execution.trace_id,
        process_score=None,
        result_score=None,
        overall_passed=False,
        details_json=None,
        status=ComparisonStatus.PROCESSING,
        error_message=None,
        retry_count=0,
    )
    await comparison_repo.create(session, comparison)
    await session.commit()

    try:
        # 执行比对
        comparison_service = ComparisonService(
            llm_client,
            comparison_repo
        )
        completed_comparison = await comparison_service.detailed_compare(
            scenario=scenario,
            execution=execution,
            trace_spans=spans,
        )

        # 更新比对结果到已创建的记录
        comparison.process_score = completed_comparison.process_score
        comparison.result_score = completed_comparison.result_score
        comparison.overall_passed = completed_comparison.overall_passed
        comparison.details_json = completed_comparison.details_json
        comparison.status = completed_comparison.status
        comparison.error_message = completed_comparison.error_message
        comparison.completed_at = datetime.utcnow()
        await session.commit()

        # 更新 execution 状态
        if comparison.overall_passed is False:
            execution.status = ExecutionStatus.COMPLETED_WITH_MISMATCH
        else:
            execution.status = ExecutionStatus.COMPLETED

        if comparison.process_score is not None and comparison.result_score is not None:
            execution.comparison_score = (comparison.process_score + comparison.result_score) / 2
        elif comparison.process_score is not None:
            execution.comparison_score = comparison.process_score
        elif comparison.result_score is not None:
            execution.comparison_score = comparison.result_score
        execution.comparison_passed = comparison.overall_passed
        await execution_repo.update(execution)

        logger.info(f"Recompare completed: {execution_id}, overall_passed={comparison.overall_passed}")
    except Exception as e:
        # 比对发生异常，更新状态为 failed
        logger.error(f"Recompare failed for execution {execution_id}: {str(e)}", exc_info=True)
        comparison.status = ComparisonStatus.FAILED
        comparison.error_message = str(e)
        comparison.completed_at = datetime.utcnow()
        await session.commit()



@router.post("/{execution_id}/recompare")
async def trigger_recompare(
    execution_id: UUID,
    background_tasks: BackgroundTasks,
    llm_model_id: Optional[UUID] = None,
    session: AsyncSession = Depends(get_db)
) -> Response[RecompareResponse]:
    """触发重新比对，后台任务执行
    - 如果提供 llm_model_id，使用指定的 LLM 模型进行验证
    - 否则使用执行记录上原有的 llm_model_id
    """
    from app.domain.repositories.execution_repo import SQLAlchemyExecutionRepository

    execution_repo = SQLAlchemyExecutionRepository(session)
    execution = await execution_repo.get_by_id(execution_id)
    if not execution:
        return Response(code=404, message="Execution not found", data=None)

    background_tasks.add_task(run_recompare, execution_id, session, llm_model_id)
    return Response[RecompareResponse](data=RecompareResponse(
        success=True,
        message="Recompare triggered in background"
    ))
