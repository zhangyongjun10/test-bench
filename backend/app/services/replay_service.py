"""End-to-end replay service."""

import json
import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.core.logger import logger
from app.domain.entities.comparison import ComparisonSourceType, ComparisonStatus
from app.domain.entities.execution import ExecutionJob, ExecutionRunSource, ExecutionStatus
from app.domain.entities.replay import ReplayBaselineSource, ReplayTask, ReplayTaskStatus
from app.domain.repositories.agent_repo import SQLAlchemyAgentRepository
from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository
from app.domain.repositories.execution_repo import SQLAlchemyExecutionRepository
from app.domain.repositories.llm_repo import SQLAlchemyLLMRepository
from app.domain.repositories.replay_repo import SQLAlchemyReplayRepository
from app.domain.repositories.scenario_repo import SQLAlchemyScenarioRepository
from app.models.replay import CreateReplayRequest
from app.services.comparison import ComparisonService, extract_llm_content
from app.services.execution_service import count_openai_llm_spans, has_tool_call_output
from app.services.llm_service import LLMService
from app.services.trace_fetcher import TraceFetcherImpl


def _openai_llm_spans(spans: list) -> list:
    return [
        span
        for span in spans
        if (getattr(span, "span_type", "") or "").lower() == "llm"
        and (getattr(span, "provider", "") or "").lower() == "openai"
    ]


def extract_final_openai_output(spans: list) -> str:
    """Extract final assistant text only when the last OpenAI LLM span is text."""
    llm_spans = _openai_llm_spans(spans)
    if not llm_spans:
        return ""

    output = getattr(llm_spans[-1], "output", "") or ""
    if has_tool_call_output(output):
        return ""
    return extract_llm_content(output).strip()


class ReplayService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.replay_repo = SQLAlchemyReplayRepository(session)
        self.execution_repo = SQLAlchemyExecutionRepository(session)
        self.agent_repo = SQLAlchemyAgentRepository(session)
        self.scenario_repo = SQLAlchemyScenarioRepository(session)
        self.llm_repo = SQLAlchemyLLMRepository(session)

    async def create_replay_task(
        self,
        request: CreateReplayRequest,
        background_tasks: BackgroundTasks,
    ) -> ReplayTask:
        existing = await self.replay_repo.get_by_idempotency_key(request.idempotency_key)
        if existing:
            return existing

        if request.baseline_source not in {
            ReplayBaselineSource.SCENARIO_BASELINE,
            ReplayBaselineSource.REFERENCE_EXECUTION,
        }:
            raise ValueError("Unsupported baseline_source")

        original_execution = await self.execution_repo.get_by_id(request.original_execution_id)
        if not original_execution:
            raise ValueError("Original execution not found")
        if original_execution.status not in {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.COMPLETED_WITH_MISMATCH,
        }:
            raise ValueError("Only completed executions can be replayed")

        agent = await self.agent_repo.get_by_id(original_execution.agent_id)
        if not agent:
            raise ValueError("Agent not found")
        scenario = await self.scenario_repo.get_by_id(original_execution.scenario_id)
        if not scenario:
            raise ValueError("Scenario not found")
        llm_model = await self.llm_repo.get_by_id(request.llm_model_id)
        if not llm_model:
            raise ValueError("LLM model not found")

        baseline_snapshot = await self._build_baseline_snapshot(request.baseline_source, original_execution, scenario)

        replay_execution_id = uuid.uuid4()
        replay_execution = ExecutionJob(
            id=replay_execution_id,
            agent_id=original_execution.agent_id,
            scenario_id=original_execution.scenario_id,
            llm_model_id=request.llm_model_id,
            user_session=f"exec_{replay_execution_id.hex}",
            run_source=ExecutionRunSource.REPLAY,
            parent_execution_id=original_execution.id,
            request_snapshot_json=json.dumps(
                {
                    "original_execution_id": str(original_execution.id),
                    "baseline_source": request.baseline_source,
                    "baseline_snapshot": baseline_snapshot,
                },
                ensure_ascii=False,
            ),
            trace_id=str(uuid.uuid4()),
            status=ExecutionStatus.QUEUED,
            original_request=original_execution.original_request or scenario.prompt,
        )
        replay_task = ReplayTask(
            original_execution_id=original_execution.id,
            replay_execution_id=replay_execution.id,
            scenario_id=scenario.id,
            agent_id=agent.id,
            baseline_source=request.baseline_source,
            baseline_snapshot_json=json.dumps(baseline_snapshot, ensure_ascii=False),
            idempotency_key=request.idempotency_key,
            llm_model_id=request.llm_model_id,
            status=ReplayTaskStatus.QUEUED,
        )

        self.session.add(replay_execution)
        self.session.add(replay_task)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.replay_repo.get_by_idempotency_key(request.idempotency_key)
            if existing:
                return existing
            raise

        await self.session.refresh(replay_task)
        background_tasks.add_task(run_replay_background, replay_task.id)
        return replay_task

    async def _build_baseline_snapshot(self, baseline_source: str, original_execution: ExecutionJob, scenario) -> dict:
        if baseline_source == ReplayBaselineSource.SCENARIO_BASELINE:
            baseline_output = (scenario.baseline_result or "").strip()
            if not baseline_output:
                raise ValueError("请先设置场景基线")
            return {
                "source": ReplayBaselineSource.SCENARIO_BASELINE,
                "baseline_output": baseline_output,
                "expected_min": scenario.llm_count_min or 0,
                "expected_max": scenario.llm_count_max if scenario.llm_count_max is not None else scenario.llm_count_min or 0,
                "scenario_id": str(scenario.id),
            }

        fetcher = TraceFetcherImpl(self.session)
        spans = await fetcher.fetch_spans(original_execution.trace_id)
        baseline_output = extract_final_openai_output(spans)
        if not baseline_output:
            raise ValueError("原始执行 Trace 中没有可提取的最终 OpenAI LLM 输出")
        openai_count = count_openai_llm_spans(spans)
        return {
            "source": ReplayBaselineSource.REFERENCE_EXECUTION,
            "baseline_output": baseline_output,
            "expected_min": openai_count,
            "expected_max": openai_count,
            "original_execution_id": str(original_execution.id),
            "original_trace_id": original_execution.trace_id,
        }

    async def run_replay(self, replay_task_id: UUID) -> None:
        claimed = await self.replay_repo.claim_queued(replay_task_id)
        if not claimed:
            logger.info("Replay task %s was already claimed or finished", replay_task_id)
            return

        replay_task = await self.replay_repo.get_by_id(replay_task_id)
        if not replay_task:
            return

        replay_task.started_at = datetime.now(UTC)
        await self.replay_repo.update(replay_task)

        try:
            from app.services.execution_service import ExecutionService

            execution_service = ExecutionService(self.session)
            await execution_service.run_execution(replay_task.replay_execution_id, auto_compare=False)

            replay_task = await self.replay_repo.get_by_id(replay_task_id)
            if not replay_task:
                return
            replay_execution = await self.execution_repo.get_by_id(replay_task.replay_execution_id)
            if not replay_execution:
                raise ValueError("Replay execution not found")
            if replay_execution.status == ExecutionStatus.FAILED:
                raise ValueError(replay_execution.error_message or "Replay execution failed")

            replay_task.status = ReplayTaskStatus.COMPARING
            await self.replay_repo.update(replay_task)

            await self._compare_replay(replay_task, replay_execution)
        except Exception as exc:
            logger.error("Replay failed: %s error=%s", replay_task_id, exc, exc_info=True)
            replay_task = await self.replay_repo.get_by_id(replay_task_id)
            if replay_task:
                replay_task.status = ReplayTaskStatus.FAILED
                replay_task.error_message = str(exc)
                replay_task.completed_at = datetime.now(UTC)
                await self.replay_repo.update(replay_task)

    async def _compare_replay(self, replay_task: ReplayTask, replay_execution: ExecutionJob) -> None:
        scenario = await self.scenario_repo.get_by_id(replay_task.scenario_id)
        if not scenario:
            raise ValueError("Scenario not found")
        llm_model = await self.llm_repo.get_by_id(replay_task.llm_model_id)
        if not llm_model:
            raise ValueError("LLM model not found")

        baseline_snapshot = json.loads(replay_task.baseline_snapshot_json)
        fetcher = TraceFetcherImpl(self.session)
        spans = await fetcher.fetch_spans(replay_execution.trace_id)

        llm_service = LLMService(self.session)
        comparison_repo = SQLAlchemyComparisonRepository()
        comparison_service = ComparisonService(llm_service.get_client(llm_model), comparison_repo)
        comparison = await comparison_service.detailed_compare_with_baseline(
            scenario=scenario,
            execution=replay_execution,
            trace_spans=spans,
            llm_model=llm_model,
            baseline_output=baseline_snapshot.get("baseline_output", ""),
            expected_min=int(baseline_snapshot.get("expected_min", 0)),
            expected_max=int(baseline_snapshot.get("expected_max", 0)),
            source_type=ComparisonSourceType.REPLAY,
            replay_task_id=replay_task.id,
            baseline_source=replay_task.baseline_source,
        )
        await comparison_repo.create(self.session, comparison)

        replay_task.comparison_id = comparison.id
        replay_task.overall_passed = comparison.overall_passed
        replay_task.status = ReplayTaskStatus.COMPLETED
        replay_task.error_message = None
        replay_task.completed_at = datetime.now(UTC)
        await self.replay_repo.update(replay_task)

    async def recompare_replay(self, replay_task_id: UUID, llm_model_id: UUID) -> None:
        replay_task = await self.replay_repo.get_by_id(replay_task_id)
        if not replay_task:
            logger.error("Replay task not found for recompare: %s", replay_task_id)
            return
        if replay_task.status != ReplayTaskStatus.COMPLETED:
            logger.error("Replay task is not completed for recompare: %s", replay_task_id)
            return
        llm_model = await self.llm_repo.get_by_id(llm_model_id)
        if not llm_model:
            logger.error("LLM model not found for replay recompare: %s", llm_model_id)
            return

        replay_task.llm_model_id = llm_model_id
        replay_task.status = ReplayTaskStatus.COMPARING
        replay_task.error_message = None
        await self.replay_repo.update(replay_task)

        replay_execution = await self.execution_repo.get_by_id(replay_task.replay_execution_id)
        if not replay_execution:
            replay_task.status = ReplayTaskStatus.FAILED
            replay_task.error_message = "Replay execution not found"
            replay_task.completed_at = datetime.now(UTC)
            await self.replay_repo.update(replay_task)
            return

        try:
            await self._compare_replay(replay_task, replay_execution)
        except Exception as exc:
            logger.error("Replay recompare failed: %s error=%s", replay_task_id, exc, exc_info=True)
            replay_task.status = ReplayTaskStatus.FAILED
            replay_task.error_message = str(exc)
            replay_task.completed_at = datetime.now(UTC)
            await self.replay_repo.update(replay_task)

    async def get_replay_task(self, replay_task_id: UUID) -> ReplayTask | None:
        return await self.replay_repo.get_by_id(replay_task_id)

    async def list_by_original_execution(self, execution_id: UUID, limit: int = 20, offset: int = 0):
        return await self.replay_repo.list_by_original_execution(execution_id, limit, offset)


async def run_replay_background(replay_task_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = ReplayService(session)
        await service.run_replay(replay_task_id)


async def recompare_replay_background(replay_task_id: UUID, llm_model_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = ReplayService(session)
        await service.recompare_replay(replay_task_id, llm_model_id)
