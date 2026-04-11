"""Replay API."""

import json
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.logger import logger
from app.domain.entities.comparison import ComparisonResult
from app.domain.entities.replay import ReplayTaskStatus
from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository
from app.domain.repositories.execution_repo import SQLAlchemyExecutionRepository
from app.models.common import Response
from app.models.comparison import DetailedComparisonResponse
from app.models.execution import ExecutionResponse
from app.models.replay import (
    CreateReplayRequest,
    ReplayDetailResponse,
    ReplayHistoryResponse,
    ReplayRecompareResponse,
    ReplayTaskResponse,
)
from app.services.replay_service import ReplayService


router = APIRouter(prefix="/api/v1/replay", tags=["replay"])


def build_comparison_response(comparison: ComparisonResult) -> DetailedComparisonResponse:
    details: Dict[str, Any] = {
        "tool_comparisons": [],
        "llm_comparison": None,
        "llm_count_check": None,
        "final_output_comparison": None,
    }
    if comparison.details_json:
        try:
            details = json.loads(comparison.details_json)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse details_json for comparison %s: %s", comparison.id, exc)

    return DetailedComparisonResponse(
        id=comparison.id,
        execution_id=comparison.execution_id,
        scenario_id=comparison.scenario_id,
        llm_model_id=comparison.llm_model_id,
        replay_task_id=comparison.replay_task_id,
        source_type=comparison.source_type,
        baseline_source=comparison.baseline_source,
        trace_id=comparison.trace_id,
        process_score=comparison.process_score,
        result_score=comparison.result_score,
        overall_passed=comparison.overall_passed,
        tool_comparisons=details.get("tool_comparisons", []),
        llm_comparison=details.get("llm_comparison"),
        llm_count_check=details.get("llm_count_check"),
        final_output_comparison=details.get("final_output_comparison"),
        status=comparison.status,
        error_message=comparison.error_message,
        retry_count=comparison.retry_count,
        created_at=comparison.created_at,
        updated_at=comparison.updated_at,
        completed_at=comparison.completed_at,
    )


@router.post("")
async def create_replay(
    request: CreateReplayRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
) -> Response[ReplayTaskResponse]:
    try:
        service = ReplayService(session)
        replay_task = await service.create_replay_task(request, background_tasks)
        return Response[ReplayTaskResponse](data=ReplayTaskResponse.model_validate(replay_task))
    except ValueError as exc:
        return Response(code=1, message=str(exc), data=None)


@router.get("/{replay_task_id}")
async def get_replay_detail(
    replay_task_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> Response[ReplayDetailResponse]:
    service = ReplayService(session)
    replay_task = await service.get_replay_task(replay_task_id)
    if not replay_task:
        return Response(code=404, message="Replay task not found", data=None)

    execution_repo = SQLAlchemyExecutionRepository(session)
    original_execution = await execution_repo.get_by_id(replay_task.original_execution_id)
    replay_execution = await execution_repo.get_by_id(replay_task.replay_execution_id)
    if not original_execution or not replay_execution:
        return Response(code=404, message="Replay execution not found", data=None)

    comparison = None
    if replay_task.comparison_id:
        comparison_repo = SQLAlchemyComparisonRepository()
        comparison_entity = await comparison_repo.get_by_id(session, replay_task.comparison_id)
        if comparison_entity:
            comparison = build_comparison_response(comparison_entity)

    return Response[ReplayDetailResponse](
        data=ReplayDetailResponse(
            replay_task=ReplayTaskResponse.model_validate(replay_task),
            original_execution=ExecutionResponse.model_validate(original_execution),
            replay_execution=ExecutionResponse.model_validate(replay_execution),
            comparison=comparison,
        )
    )


@router.post("/{replay_task_id}/recompare")
async def recompare_replay(
    replay_task_id: UUID,
    background_tasks: BackgroundTasks,
    llm_model_id: UUID = Query(...),
    session: AsyncSession = Depends(get_db),
) -> Response[ReplayRecompareResponse]:
    service = ReplayService(session)
    replay_task = await service.get_replay_task(replay_task_id)
    if not replay_task:
        return Response(code=404, message="Replay task not found", data=None)
    if replay_task.status != ReplayTaskStatus.COMPLETED:
        return Response(code=1, message="回放任务完成后才能重新比对", data=None)

    from app.services.replay_service import recompare_replay_background

    background_tasks.add_task(recompare_replay_background, replay_task_id, llm_model_id)
    return Response[ReplayRecompareResponse](
        data=ReplayRecompareResponse(success=True, message="Replay recompare triggered in background")
    )


history_router = APIRouter(prefix="/api/v1/execution", tags=["replay"])


@history_router.get("/{execution_id}/replays")
async def list_execution_replays(
    execution_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> Response[ReplayHistoryResponse]:
    service = ReplayService(session)
    total, items = await service.list_by_original_execution(execution_id, limit, offset)
    return Response[ReplayHistoryResponse](
        data=ReplayHistoryResponse(
            total=total,
            items=[ReplayTaskResponse.model_validate(item) for item in items],
        )
    )
