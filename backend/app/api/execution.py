"""Execution API"""

import asyncio
import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.logger import logger
from app.domain.entities.comparison import ComparisonSourceType, ComparisonStatus
from app.domain.entities.execution import ExecutionStatus
from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository
from app.domain.repositories.execution_repo import SQLAlchemyExecutionRepository
from app.domain.repositories.scenario_repo import SQLAlchemyScenarioRepository
from app.models.common import ListResponse, Response
from app.models.comparison import DetailedComparisonResponse, RecompareResponse
from app.models.execution import (
    ConcurrentExecutionRequest,
    ConcurrentExecutionResponse,
    CreateExecutionRequest,
    ExecutionResponse,
    ExecutionTraceResponse,
    SpanResponse,
)
from app.services.comparison import ComparisonService
from app.services.concurrent_execution_service import ConcurrentExecutionMode, ConcurrentExecutionService
from app.services.execution_service import ExecutionService, count_openai_llm_spans, is_trace_ready_for_comparison
from app.services.llm_service import LLMService
from app.services.trace_fetcher import TraceFetcherImpl


router = APIRouter(prefix="/api/v1/execution", tags=["execution"])


@router.post("")
async def create_execution(request: CreateExecutionRequest, background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_db)) -> Response[UUID]:
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
    session: AsyncSession = Depends(get_db),
) -> Response[ListResponse[ExecutionResponse]]:
    service = ExecutionService(session)
    total, executions = await service.list_executions(agent_id, scenario_id, limit, offset)
    return Response[ListResponse[ExecutionResponse]](
        data=ListResponse[ExecutionResponse](total=total, items=[ExecutionResponse.model_validate(e) for e in executions])
    )


@router.get("/{execution_id}")
async def get_execution(execution_id: UUID, session: AsyncSession = Depends(get_db)) -> Response[ExecutionResponse]:
    service = ExecutionService(session)
    execution = await service.get_execution(execution_id)
    if not execution:
        return Response(code=404, message="Execution not found", data=None)
    return Response[ExecutionResponse](data=ExecutionResponse.model_validate(execution))


@router.get("/{execution_id}/trace")
async def get_trace(execution_id: UUID, session: AsyncSession = Depends(get_db)) -> Response[ExecutionTraceResponse]:
    service = ExecutionService(session)
    execution = await service.get_execution(execution_id)
    if not execution:
        return Response(code=404, message="Execution not found", data=None)

    fetcher = TraceFetcherImpl(session)
    spans = await fetcher.fetch_spans(execution.trace_id)
    span_responses = [
        SpanResponse(
            span_id=span.span_id,
            span_type=span.span_type,
            name=span.name,
            provider=getattr(span, "provider", None),
            input_tokens=span.metrics.input_tokens,
            output_tokens=span.metrics.output_tokens,
            input=span.input,
            output=span.output,
            duration_ms=span.duration_ms,
            ttft_ms=span.metrics.ttft_ms,
            tpot_ms=span.metrics.tpot_ms,
        )
        for span in spans
    ]
    return Response[ExecutionTraceResponse](data=ExecutionTraceResponse(trace_id=execution.trace_id, spans=span_responses))


@router.delete("/{execution_id}")
async def delete_execution(execution_id: UUID, session: AsyncSession = Depends(get_db)) -> Response[None]:
    service = ExecutionService(session)
    success = await service.delete_execution(execution_id)
    if not success:
        return Response(code=404, message="Execution not found", data=None)
    return Response[None](code=0, message="Deleted", data=None)


@router.get("/{execution_id}/comparison")
async def get_comparison(execution_id: UUID, session: AsyncSession = Depends(get_db)) -> Response[DetailedComparisonResponse]:
    comparison_repo = SQLAlchemyComparisonRepository()
    comparison = await comparison_repo.get_by_execution_id(session, execution_id)
    if not comparison:
        return Response(code=404, message="Comparison not found", data=None)

    details: Dict[str, Any] = {"tool_comparisons": [], "llm_comparison": None, "llm_count_check": None, "final_output_comparison": None}
    if comparison.details_json:
        try:
            details = json.loads(comparison.details_json)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse details_json for comparison %s: %s", execution_id, e)

    response = DetailedComparisonResponse(
        id=comparison.id,
        execution_id=comparison.execution_id,
        scenario_id=comparison.scenario_id,
        llm_model_id=comparison.llm_model_id,
        replay_task_id=getattr(comparison, "replay_task_id", None),
        source_type=getattr(comparison, "source_type", None),
        baseline_source=getattr(comparison, "baseline_source", None),
        trace_id=comparison.trace_id,
        process_score=comparison.process_score,
        result_score=comparison.result_score,
        overall_passed=comparison.overall_passed,
        tool_comparisons=details.get("tool_comparisons", []),
        llm_comparison=details.get("llm_comparison"),
        llm_count_check=details.get("llm_count_check"),
        final_output_comparison=(
            details.get("final_output_comparison")
            or (
                {
                    "baseline_output": details["llm_comparison"].get("baseline_output", ""),
                    "actual_output": details["llm_comparison"].get("actual_output", ""),
                    "consistent": details["llm_comparison"].get("consistent", False),
                    "reason": details["llm_comparison"].get("reason", ""),
                }
                if isinstance(details.get("llm_comparison"), dict)
                else None
            )
        ),
        status=comparison.status,
        error_message=comparison.error_message,
        retry_count=comparison.retry_count,
        created_at=comparison.created_at,
        updated_at=comparison.updated_at,
        completed_at=comparison.completed_at,
    )
    return Response[DetailedComparisonResponse](data=response)


@router.get("/{execution_id}/comparisons")
async def list_comparisons(execution_id: UUID, session: AsyncSession = Depends(get_db)) -> Response[List[DetailedComparisonResponse]]:
    comparison_repo = SQLAlchemyComparisonRepository()
    comparisons = await comparison_repo.list_by_execution_id(session, execution_id)

    items: List[DetailedComparisonResponse] = []
    for comparison in comparisons:
        details: Dict[str, Any] = {"tool_comparisons": [], "llm_comparison": None, "llm_count_check": None, "final_output_comparison": None}
        if comparison.details_json:
            try:
                details = json.loads(comparison.details_json)
            except json.JSONDecodeError as e:
                logger.error("Failed to parse details_json for comparison %s: %s", comparison.id, e)

        items.append(
            DetailedComparisonResponse(
                id=comparison.id,
                execution_id=comparison.execution_id,
                scenario_id=comparison.scenario_id,
                llm_model_id=comparison.llm_model_id,
                replay_task_id=getattr(comparison, "replay_task_id", None),
                source_type=getattr(comparison, "source_type", None),
                baseline_source=getattr(comparison, "baseline_source", None),
                trace_id=comparison.trace_id,
                process_score=comparison.process_score,
                result_score=comparison.result_score,
                overall_passed=comparison.overall_passed,
                tool_comparisons=details.get("tool_comparisons", []),
                llm_comparison=details.get("llm_comparison"),
                llm_count_check=details.get("llm_count_check"),
                final_output_comparison=(
                    details.get("final_output_comparison")
                    or (
                        {
                            "baseline_output": details["llm_comparison"].get("baseline_output", ""),
                            "actual_output": details["llm_comparison"].get("actual_output", ""),
                            "consistent": details["llm_comparison"].get("consistent", False),
                            "reason": details["llm_comparison"].get("reason", ""),
                        }
                        if isinstance(details.get("llm_comparison"), dict)
                        else None
                    )
                ),
                status=comparison.status,
                error_message=comparison.error_message,
                retry_count=comparison.retry_count,
                created_at=comparison.created_at,
                updated_at=comparison.updated_at,
                completed_at=comparison.completed_at,
            )
        )

    return Response[List[DetailedComparisonResponse]](data=items)


async def run_recompare(execution_id: UUID, llm_model_id: UUID) -> None:
    from app.core.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await _run_recompare_with_session(session, execution_id, llm_model_id)


async def _run_recompare_with_session(session: AsyncSession, execution_id: UUID, llm_model_id: UUID) -> None:
    from datetime import UTC, datetime

    from app.domain.entities.comparison import ComparisonResult, ComparisonStatus

    execution_repo = SQLAlchemyExecutionRepository(session)
    execution = await execution_repo.get_by_id(execution_id)
    if not execution:
        logger.error("Execution not found for recompare: %s", execution_id)
        return

    scenario_repo = SQLAlchemyScenarioRepository(session)
    scenario = await scenario_repo.get_by_id(execution.scenario_id)
    if not scenario:
        logger.error("Scenario not found for recompare: %s", execution.scenario_id)
        return

    llm_service = LLMService(session)
    llm_model = await llm_service.get_llm(llm_model_id)
    if not llm_model:
        logger.error("LLM model not found for recompare: %s", llm_model_id)
        return

    llm_client = llm_service.get_client(llm_model)
    comparison_repo = SQLAlchemyComparisonRepository()
    comparison = ComparisonResult(
        execution_id=execution.id,
        scenario_id=scenario.id,
        llm_model_id=llm_model_id,
        trace_id=execution.trace_id,
        source_type=ComparisonSourceType.RECOMPARE,
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

    trace_fetcher = TraceFetcherImpl(session)
    spans = []
    retry_delays = [0, 2, 4, 8, 15, 30]
    expected_min_llm_count = scenario.llm_count_min or 0
    compare_enabled = getattr(scenario, "compare_enabled", True)
    for index, delay in enumerate(retry_delays):
        if delay:
            logger.info("Trace not ready for recompare, waiting %ss before retry (%s/%s)...", delay, index, len(retry_delays) - 1)
            await asyncio.sleep(delay)
        spans = await trace_fetcher.fetch_spans(execution.trace_id)
        if not compare_enabled or is_trace_ready_for_comparison(spans, expected_min_llm_count):
            break
        logger.info(
            "Trace has %s spans and %s OpenAI LLM spans, but recompare is not ready yet for execution %s",
            len(spans),
            count_openai_llm_spans(spans),
            execution_id,
        )

    try:
        comparison_service = ComparisonService(llm_client, comparison_repo)
        completed_comparison = await comparison_service.detailed_compare(
            scenario=scenario,
            execution=execution,
            trace_spans=spans,
            llm_model=llm_model,
        )
        comparison.process_score = completed_comparison.process_score
        comparison.result_score = completed_comparison.result_score
        comparison.overall_passed = completed_comparison.overall_passed
        comparison.llm_model_id = completed_comparison.llm_model_id
        comparison.source_type = ComparisonSourceType.RECOMPARE
        comparison.details_json = completed_comparison.details_json
        comparison.status = completed_comparison.status
        comparison.error_message = completed_comparison.error_message
        comparison.completed_at = datetime.now(UTC)
        await session.commit()

        execution.status = ExecutionStatus.COMPLETED_WITH_MISMATCH if comparison.overall_passed is False else ExecutionStatus.COMPLETED
        execution.comparison_score = None
        execution.comparison_passed = comparison.overall_passed
        execution.error_message = None
        await execution_repo.update(execution)
    except Exception as e:
        logger.error("Recompare failed for execution %s: %s", execution_id, str(e), exc_info=True)
        comparison.status = ComparisonStatus.FAILED
        comparison.error_message = str(e)
        comparison.completed_at = datetime.now(UTC)
        await session.commit()


@router.post("/{execution_id}/recompare")
async def trigger_recompare(
    execution_id: UUID,
    background_tasks: BackgroundTasks,
    llm_model_id: UUID = Query(...),
    session: AsyncSession = Depends(get_db),
) -> Response[RecompareResponse]:
    execution_repo = SQLAlchemyExecutionRepository(session)
    execution = await execution_repo.get_by_id(execution_id)
    if not execution:
        return Response(code=404, message="Execution not found", data=None)

    llm_service = LLMService(session)
    llm_model = await llm_service.get_llm(llm_model_id)
    if not llm_model:
        return Response(code=404, message="LLM model not found", data=None)

    background_tasks.add_task(run_recompare, execution_id, llm_model_id)
    return Response[RecompareResponse](data=RecompareResponse(success=True, message="Recompare triggered in background"))


@router.post("/concurrent")
async def create_concurrent_execution(
    request: ConcurrentExecutionRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
) -> Response[ConcurrentExecutionResponse]:
    try:
        mode = request.concurrent_mode or ConcurrentExecutionMode.SINGLE_INSTANCE
        service = ConcurrentExecutionService(session, mode=mode)
        batch_id = await service.create_concurrent_execution(
            request.input,
            request.concurrency,
            request.model,
            background_tasks,
            request.scenario_id,
            mode,
            request.llm_model_id,
            request.agent_id,
        )
        return Response[ConcurrentExecutionResponse](data=ConcurrentExecutionResponse(batch_id=batch_id, message="Concurrent execution started"))
    except ValueError as e:
        return Response(code=1, message=str(e), data=None)


@router.get("/concurrent/{batch_id}")
async def get_concurrent_execution_status(batch_id: str, session: AsyncSession = Depends(get_db)) -> Response[dict]:
    try:
        service = ConcurrentExecutionService(session)
        status = await service.get_concurrent_execution_status(batch_id)
        return Response[dict](data=status)
    except Exception as e:
        return Response(code=1, message=str(e), data=None)
