"""Execution service."""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Optional
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.http_agent_client import HTTPAgentClient
from app.config import settings
from app.core.db import AsyncSessionLocal
from app.core.encryption import encryption_service
from app.core.logger import logger
from app.core.metrics import increment_executions_total, observe_execution_duration
from app.domain.entities.comparison import ComparisonResult, ComparisonSourceType, ComparisonStatus
from app.domain.entities.execution import ExecutionJob, ExecutionRunSource, ExecutionStatus
from app.domain.repositories.agent_repo import SQLAlchemyAgentRepository
from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository
from app.domain.repositories.execution_repo import ExecutionRepository, SQLAlchemyExecutionRepository
from app.domain.repositories.scenario_repo import SQLAlchemyScenarioRepository
from app.models.execution import CreateExecutionRequest
from app.services.llm_service import LLMService


def has_comparable_llm_output(spans: list) -> bool:
    return has_final_openai_llm_output(spans)


def has_tool_call_output(output: str) -> bool:
    if not output:
        return False
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    choices = parsed.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict) and (message.get("tool_calls") or message.get("function_call")):
            return True
        delta = choice.get("delta")
        if isinstance(delta, dict) and (delta.get("tool_calls") or delta.get("function_call")):
            return True
    return False


def has_final_openai_llm_output(spans: list) -> bool:
    from app.services.comparison import extract_llm_content

    llm_spans = [
        span
        for span in spans
        if (getattr(span, "span_type", "") or "").lower() == "llm"
        and (getattr(span, "provider", "") or "").lower() == "openai"
    ]
    if not llm_spans:
        return False
    output = getattr(llm_spans[-1], "output", "") or ""
    return bool(extract_llm_content(output).strip()) and not has_tool_call_output(output)


def count_openai_llm_spans(spans: list) -> int:
    return sum(
        1
        for span in spans
        if (getattr(span, "span_type", "") or "").lower() == "llm"
        and (getattr(span, "provider", "") or "").lower() == "openai"
    )


def is_trace_ready_for_comparison(spans: list, expected_min_llm_count: int) -> bool:
    del expected_min_llm_count
    return has_final_openai_llm_output(spans)


class ExecutionService:
    def __init__(self, session: AsyncSession):
        """初始化执行链路依赖，确保 Agent、Case 与执行仓储共享同一会话。"""

        self.repo: ExecutionRepository = SQLAlchemyExecutionRepository(session)
        self.agent_repo = SQLAlchemyAgentRepository(session)
        self.scenario_repo = SQLAlchemyScenarioRepository(session)
        self.session = session

    async def create_execution(self, request: CreateExecutionRequest, background_tasks: BackgroundTasks) -> UUID:
        """创建执行前校验 Agent 与 Case 绑定关系，避免未授权组合进入执行链路。"""

        agent = await self.agent_repo.get_by_id(request.agent_id)
        if not agent:
            raise ValueError(f"Agent {request.agent_id} not found")

        scenario = await self.scenario_repo.get_by_id(request.scenario_id)
        if not scenario:
            raise ValueError(f"Scenario {request.scenario_id} not found")
        if not await self.scenario_repo.is_bound_to_agent(request.scenario_id, request.agent_id):
            raise ValueError(f"Scenario {request.scenario_id} is not bound to agent {request.agent_id}")

        if request.llm_model_id:
            llm_service = LLMService(self.session)
            llm_model = await llm_service.get_llm(request.llm_model_id)
            if not llm_model:
                raise ValueError(f"LLM model {request.llm_model_id} not found")

        execution_id = uuid.uuid4()
        execution = ExecutionJob(
            id=execution_id,
            agent_id=request.agent_id,
            scenario_id=request.scenario_id,
            llm_model_id=request.llm_model_id,
            user_session=f"exec_{execution_id.hex}",
            run_source=ExecutionRunSource.NORMAL,
            batch_id=None,
            trace_id=str(uuid.uuid4()),
            status=ExecutionStatus.QUEUED,
        )
        result = await self.repo.create(execution)
        logger.info("Created execution job: %s trace_id=%s", result.id, result.trace_id)

        background_tasks.add_task(_run_execution_background, result.id)
        return result.id

    async def run_execution(self, execution_id: UUID, *, auto_compare: bool = True) -> None:
        from app.services.comparison import ComparisonService
        from app.services.metric_extractor import MetricExtractor
        from app.services.trace_fetcher import TraceFetcherImpl

        started_at = time.time()
        execution = await self.repo.get_by_id(execution_id)
        if not execution:
            logger.error("Execution not found: %s", execution_id)
            return

        try:
            execution.status = ExecutionStatus.RUNNING
            execution.started_at = datetime.now(UTC)
            await self.repo.update(execution)

            agent = await self.agent_repo.get_by_id(execution.agent_id)
            if not agent:
                raise ValueError(f"Agent {execution.agent_id} not found")

            scenario = await self.scenario_repo.get_by_id(execution.scenario_id)
            if not scenario:
                raise ValueError(f"Scenario {execution.scenario_id} not found")

            api_key = encryption_service.decrypt(agent.api_key_encrypted)
            client = HTTPAgentClient(
                agent.base_url,
                api_key,
                timeout=settings.agent_timeout_seconds,
                user_session=execution.user_session,
            )

            execution.original_request = scenario.prompt
            response_content, response_data = await client.invoke(scenario.prompt, execution.trace_id)
            execution.original_response = response_content

            if response_data and isinstance(response_data, dict) and "id" in response_data:
                run_id = str(response_data["id"])
                trace_fetcher = TraceFetcherImpl(self.session)
                real_trace_id = await trace_fetcher.get_trace_id_by_run_id(run_id)
                execution.trace_id = real_trace_id or run_id
                await self.repo.update(execution)

            execution.status = ExecutionStatus.PULLING_TRACE
            await self.repo.update(execution)

            trace_fetcher = TraceFetcherImpl(self.session)
            spans = []
            retry_delays = [0, 2, 4, 8, 15, 30]
            expected_min_llm_count = scenario.llm_count_min or 0
            for index, delay in enumerate(retry_delays):
                if delay:
                    logger.info("Trace not ready, waiting %ss before retry (%s/%s)...", delay, index, len(retry_delays) - 1)
                    await asyncio.sleep(delay)
                spans = await trace_fetcher.fetch_spans(execution.trace_id)
                if spans and (not scenario.compare_enabled or is_trace_ready_for_comparison(spans, expected_min_llm_count)):
                    break
                if spans and scenario.compare_enabled:
                    logger.info(
                        "Trace has %s spans and %s OpenAI LLM spans, but comparison is not ready yet for execution %s",
                        len(spans),
                        count_openai_llm_spans(spans),
                        execution_id,
                    )

            extractor = MetricExtractor()
            extractor.extract(spans)

            if auto_compare:
                execution.status = ExecutionStatus.COMPARING
                await self.repo.update(execution)

            overall_passed: Optional[bool] = None
            if auto_compare and scenario.compare_enabled and execution.llm_model_id:
                llm_service = LLMService(self.session)
                llm_model = await llm_service.get_llm(execution.llm_model_id)
                if not llm_model:
                    raise ValueError(f"LLM model {execution.llm_model_id} not found")

                comparison_repo = SQLAlchemyComparisonRepository()
                comparison_service = ComparisonService(llm_service.get_client(llm_model), comparison_repo)

                try:
                    comparison_result = await comparison_service.detailed_compare(
                        scenario=scenario,
                        execution=execution,
                        trace_spans=spans,
                        llm_model=llm_model,
                    )
                    comparison_result.source_type = ComparisonSourceType.EXECUTION_AUTO
                    await comparison_repo.create(self.session, comparison_result)
                    execution.comparison_score = None
                    execution.comparison_passed = comparison_result.overall_passed
                    overall_passed = comparison_result.overall_passed
                except Exception as exc:
                    logger.error("Detailed comparison failed for execution %s: %s", execution_id, exc, exc_info=True)
                    await comparison_repo.create(
                        self.session,
                        ComparisonResult(
                            execution_id=execution.id,
                            scenario_id=scenario.id,
                            llm_model_id=execution.llm_model_id,
                            trace_id=execution.trace_id,
                            source_type=ComparisonSourceType.EXECUTION_AUTO,
                            process_score=None,
                            result_score=None,
                            overall_passed=False,
                            details_json=None,
                            status=ComparisonStatus.FAILED,
                            error_message=str(exc),
                            retry_count=0,
                        ),
                    )
                    execution.comparison_score = None
                    execution.comparison_passed = None

            execution.status = ExecutionStatus.COMPLETED_WITH_MISMATCH if overall_passed is False else ExecutionStatus.COMPLETED
            execution.completed_at = datetime.now(UTC)
            await self.repo.update(execution)

            duration = time.time() - started_at
            increment_executions_total(status=ExecutionStatus.COMPLETED)
            observe_execution_duration(duration)
        except Exception as exc:
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(exc)
            execution.completed_at = datetime.now(UTC)
            await self.repo.update(execution)

            duration = time.time() - started_at
            increment_executions_total(status=ExecutionStatus.FAILED)
            observe_execution_duration(duration)
            logger.error("Execution failed: %s error=%s", execution_id, exc, exc_info=True)

    async def get_execution(self, execution_id: UUID) -> Optional[ExecutionJob]:
        return await self.repo.get_by_id(execution_id)

    # 执行列表查询透传比对结果筛选条件，由仓储层统一做数据库过滤，避免前端仅筛当前页导致总数和分页错位。
    async def list_executions(
        self,
        agent_id: Optional[UUID] = None,
        scenario_id: Optional[UUID] = None,
        trace_id: Optional[str] = None,
        comparison_result: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[int, list[ExecutionJob]]:
        return await self.repo.list_all(
            agent_id,
            scenario_id,
            trace_id,
            comparison_result,
            limit,
            offset,
        )

    async def delete_execution(self, execution_id: UUID) -> bool:
        execution = await self.repo.get_by_id(execution_id)
        if not execution:
            return False
        comparison_repo = SQLAlchemyComparisonRepository()
        deleted_count = await comparison_repo.delete_by_execution_id(self.session, execution_id)
        await self.repo.delete(execution_id)
        logger.info("Deleted execution: %s (removed %s comparison rows first)", execution_id, deleted_count)
        return True


async def _run_execution_background(execution_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        service = ExecutionService(session)
        await service.run_execution(execution_id)
