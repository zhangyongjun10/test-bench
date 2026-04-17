"""Concurrent execution service for OpenClaw requests."""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.http_agent_client import HTTPAgentClient
from app.config import settings
from app.core.db import AsyncSessionLocal
from app.core.encryption import encryption_service
from app.core.logger import logger
from app.core.metrics import increment_executions_total, observe_execution_duration
from app.domain.entities.agent import Agent
from app.domain.entities.comparison import ComparisonResult, ComparisonSourceType, ComparisonStatus
from app.domain.entities.execution import ExecutionJob, ExecutionRunSource, ExecutionStatus
from app.domain.repositories.agent_repo import SQLAlchemyAgentRepository
from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository
from app.domain.repositories.execution_repo import ExecutionRepository, SQLAlchemyExecutionRepository
from app.domain.repositories.scenario_repo import SQLAlchemyScenarioRepository
from app.services.comparison import ComparisonService
from app.services.llm_service import LLMService
from app.services.trace_fetcher import TraceFetcherImpl


# 并发执行服务，负责为同一个场景创建多条隔离 user_session 的 Agent 执行记录。
class ConcurrentExecutionService:
    # Agent 请求固定使用 OpenClaw 主入口模型，避免把页面选择的比对模型误传给 Agent。
    AGENT_REQUEST_MODEL = "openclaw:main"
    TRACE_FETCH_RETRIES = 5
    TRACE_FETCH_RETRY_INTERVAL_SECONDS = 2.0
    TRACE_ID_RESOLUTION_RETRIES = 5
    TRACE_ID_RESOLUTION_RETRY_INTERVAL_SECONDS = 2.0
    DEFERRED_COMPARISON_RETRIES = 12
    DEFERRED_COMPARISON_RETRY_INTERVAL_SECONDS = 5.0

    # 初始化并发执行服务，所有并发请求统一按多路独立 execution 执行。
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo: ExecutionRepository = SQLAlchemyExecutionRepository(session)

    # 构建 Agent HTTP 客户端，正式执行超时使用全局 Agent 超时配置。
    def _build_client(self, agent: Agent) -> HTTPAgentClient:
        api_key = encryption_service.decrypt(agent.api_key_encrypted)
        return HTTPAgentClient(
            agent.base_url,
            api_key,
            timeout=settings.agent_timeout_seconds,
            user_session=agent.user_session,
            verify_ssl=False,
        )

    # 创建并发执行批次并注册后台任务，前端只需传入并发数和比对模型。
    async def create_concurrent_execution(
        self,
        input_text: str,
        concurrency: int,
        background_tasks: BackgroundTasks,
        scenario_id: UUID,
        llm_model_id: UUID | None,
        agent_id: UUID,
    ) -> str:
        if not input_text:
            raise ValueError("input cannot be empty")
        if concurrency <= 0:
            raise ValueError("concurrency must be greater than 0")
        if not scenario_id:
            raise ValueError("scenario_id is required")
        if not agent_id:
            raise ValueError("agent_id is required")

        batch_id = str(uuid.uuid4())
        background_tasks.add_task(
            self.run_concurrent_execution,
            batch_id,
            input_text,
            concurrency,
            scenario_id,
            llm_model_id,
            agent_id,
        )
        return batch_id

    # 后台运行并发执行批次，为每一路并发创建独立 execution、user_session 和 trace_id。
    async def run_concurrent_execution(
        self,
        batch_id: str,
        input_text: str,
        concurrency: int,
        scenario_id: UUID,
        llm_model_id: UUID | None,
        agent_id: UUID,
    ) -> None:
        async with AsyncSessionLocal() as session:
            try:
                agent_repo = SQLAlchemyAgentRepository(session)
                agent = await agent_repo.get_by_id(agent_id)
                if not agent:
                    logger.error("Agent %s not found for batch %s", agent_id, batch_id)
                    return

                await self._run_concurrent_calls(batch_id, input_text, concurrency, scenario_id, llm_model_id, agent)
            except Exception as exc:
                logger.error("Concurrent execution failed: %s error=%s", batch_id, exc, exc_info=True)

    # 统一执行并发调用，每一路独立创建客户端和数据库 Session，避免共享状态造成串扰。
    async def _run_concurrent_calls(
        self,
        batch_id: str,
        input_text: str,
        concurrency: int,
        scenario_id: UUID,
        llm_model_id: UUID | None,
        agent: Agent,
    ) -> None:
        async def execute_with_own_session(call_index: int):
            async with AsyncSessionLocal() as session:
                local_repo = SQLAlchemyExecutionRepository(session)
                client = self._build_client(agent)
                return await self._execute_single_call(
                    batch_id=batch_id,
                    input_text=input_text,
                    scenario_id=scenario_id,
                    llm_model_id=llm_model_id,
                    agent=agent,
                    client=client,
                    repo=local_repo,
                    call_index=call_index,
                )

        await asyncio.gather(
            *(execute_with_own_session(i + 1) for i in range(concurrency)),
            return_exceptions=True,
        )

    # 执行单路并发调用并落库，user_session 统一使用 exec_{execution_id} 保持会话隔离。
    async def _execute_single_call(
        self,
        *,
        batch_id: str,
        input_text: str,
        scenario_id: UUID,
        llm_model_id: UUID | None,
        agent: Agent,
        client: HTTPAgentClient,
        repo: ExecutionRepository,
        call_index: int,
    ) -> dict[str, Any]:
        start_time = time.time()
        execution_id = uuid.uuid4()
        user_session = f"exec_{execution_id.hex}"
        execution = ExecutionJob(
            id=execution_id,
            agent_id=agent.id,
            scenario_id=scenario_id,
            llm_model_id=llm_model_id,
            user_session=user_session,
            run_source=ExecutionRunSource.NORMAL,
            parent_execution_id=None,
            request_snapshot_json=None,
            trace_id=str(uuid.uuid4()),
            status=ExecutionStatus.QUEUED,
            batch_id=batch_id,
            original_request=input_text,
        )
        execution = await repo.create(execution)

        try:
            execution.status = ExecutionStatus.RUNNING
            execution.started_at = datetime.now(UTC)
            await repo.update(execution)
            request_trace_id = execution.trace_id

            response_content, response_data = await client.invoke(
                input_text,
                request_trace_id,
                model=self.AGENT_REQUEST_MODEL,
                user_session=user_session,
            )
            execution.original_response = response_content

            if response_data and isinstance(response_data, dict) and response_data.get("id") is not None:
                run_id = str(response_data["id"])
                real_trace_id = await self._resolve_trace_id_with_retry(
                    repo.session,
                    run_id,
                    retries=self.TRACE_ID_RESOLUTION_RETRIES,
                    interval_seconds=self.TRACE_ID_RESOLUTION_RETRY_INTERVAL_SECONDS,
                )
                execution.trace_id = real_trace_id or request_trace_id
                await repo.update(execution)

            comparison_ran = False
            comparison_passed: bool | None = None
            if llm_model_id:
                execution.status = ExecutionStatus.PULLING_TRACE
                await repo.update(execution)
                comparison_ran, comparison_passed = await self._run_comparison(
                    repo.session,
                    execution,
                    scenario_id,
                    llm_model_id,
                )

            execution.status = (
                ExecutionStatus.COMPLETED_WITH_MISMATCH
                if comparison_ran and comparison_passed is False
                else ExecutionStatus.COMPLETED
            )
            execution.completed_at = datetime.now(UTC)
            await repo.update(execution)

            duration = time.time() - start_time
            increment_executions_total(status=ExecutionStatus.COMPLETED)
            observe_execution_duration(duration)
            return {"execution_id": execution.id, "call_index": call_index, "success": True}
        except Exception as exc:
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(exc)
            execution.completed_at = datetime.now(UTC)
            await repo.update(execution)
            duration = time.time() - start_time
            increment_executions_total(status=ExecutionStatus.FAILED)
            observe_execution_duration(duration)
            logger.error("Concurrent execution call failed: %s", exc, exc_info=True)
            return {"execution_id": execution.id, "call_index": call_index, "success": False}

    # 为并发执行结果触发比对；如果 Trace 尚未就绪，会写入处理中比对记录并安排延迟重试。
    async def _run_comparison(
        self,
        session: AsyncSession,
        execution: ExecutionJob,
        scenario_id: UUID,
        llm_model_id: UUID,
        spans: Optional[list] = None,
    ) -> tuple[bool, Optional[bool]]:
        scenario_repo = SQLAlchemyScenarioRepository(session)
        scenario = await scenario_repo.get_by_id(scenario_id)
        if not scenario or not scenario.compare_enabled:
            return False, None

        llm_service = LLMService(session)
        llm_model = await llm_service.get_llm(llm_model_id)
        if not llm_model:
            logger.warning("LLM model %s not found for execution %s", llm_model_id, execution.id)
            return False, None

        spans = spans or await self._fetch_spans_with_retry(session, execution)
        if not spans:
            if execution.original_response:
                spans = []
            else:
                await self._upsert_pending_comparison(
                    session,
                    execution,
                    scenario_id,
                    "Trace spans not ready yet; deferred comparison scheduled.",
                )
                self._schedule_deferred_comparison(execution.id, scenario_id, llm_model_id)
                return False, None

        execution.status = ExecutionStatus.COMPARING
        await SQLAlchemyExecutionRepository(session).update(execution)

        comparison_repo = SQLAlchemyComparisonRepository()
        comparison_service = ComparisonService(
            llm_service.get_client(llm_model),
            comparison_repo,
        )
        comparison_result = await comparison_service.detailed_compare(
            scenario=scenario,
            execution=execution,
            trace_spans=spans,
            llm_model=llm_model,
        )
        comparison_result.source_type = ComparisonSourceType.EXECUTION_AUTO
        await comparison_repo.create(session, comparison_result)

        execution.comparison_score = None
        execution.comparison_passed = comparison_result.overall_passed
        await SQLAlchemyExecutionRepository(session).update(execution)
        return True, comparison_result.overall_passed

    # 安排延迟比对任务，避免 Trace 异步落库慢导致当前批次立即误判。
    def _schedule_deferred_comparison(self, execution_id: UUID, scenario_id: UUID, llm_model_id: UUID) -> None:
        asyncio.create_task(self._run_deferred_comparison(execution_id, scenario_id, llm_model_id))

    # 执行延迟比对任务，等待 Trace 后复用并发执行的比对逻辑更新执行状态。
    async def _run_deferred_comparison(self, execution_id: UUID, scenario_id: UUID, llm_model_id: UUID) -> None:
        async with AsyncSessionLocal() as session:
            execution_repo = SQLAlchemyExecutionRepository(session)
            execution = await execution_repo.get_by_id(execution_id)
            if not execution:
                return

            spans = await self._fetch_spans_with_retry(
                session,
                execution,
                retries=self.DEFERRED_COMPARISON_RETRIES,
                interval_seconds=self.DEFERRED_COMPARISON_RETRY_INTERVAL_SECONDS,
            )
            if not spans:
                return

            comparison_ran, comparison_passed = await self._run_comparison(
                session,
                execution,
                scenario_id,
                llm_model_id,
                spans=spans,
            )
            if not comparison_ran:
                return

            execution = await execution_repo.get_by_id(execution_id)
            if not execution:
                return
            execution.status = (
                ExecutionStatus.COMPLETED_WITH_MISMATCH
                if comparison_passed is False
                else ExecutionStatus.COMPLETED
            )
            await execution_repo.update(execution)

    # 带重试拉取执行 Trace，用于等待 OpenClaw/Opik 异步写入 span。
    async def _fetch_spans_with_retry(
        self,
        session: AsyncSession,
        execution: ExecutionJob,
        retries: Optional[int] = None,
        interval_seconds: Optional[float] = None,
    ) -> list:
        trace_fetcher = TraceFetcherImpl(session)
        retries = retries or self.TRACE_FETCH_RETRIES
        interval_seconds = interval_seconds or self.TRACE_FETCH_RETRY_INTERVAL_SECONDS
        for attempt in range(1, retries + 1):
            spans = await trace_fetcher.fetch_spans(execution.trace_id)
            if spans:
                return spans
            if attempt < retries:
                await asyncio.sleep(interval_seconds)
        return []

    # 根据 Agent 返回的 run_id 反查真实 trace_id，解决 OpenClaw 响应 ID 与 Opik trace_id 不一致的问题。
    async def _resolve_trace_id_with_retry(
        self,
        session: AsyncSession,
        run_id: str,
        retries: int,
        interval_seconds: float,
    ) -> Optional[str]:
        trace_fetcher = TraceFetcherImpl(session)
        for attempt in range(1, retries + 1):
            real_trace_id = await trace_fetcher.get_trace_id_by_run_id(run_id)
            if real_trace_id:
                return real_trace_id
            if attempt < retries:
                await asyncio.sleep(interval_seconds)
        return None

    # 写入或更新处理中比对记录，提示前端当前 Trace 尚未准备好。
    async def _upsert_pending_comparison(
        self,
        session: AsyncSession,
        execution: ExecutionJob,
        scenario_id: UUID,
        message: str,
    ) -> None:
        comparison_repo = SQLAlchemyComparisonRepository()
        existing = await comparison_repo.get_by_execution_id(session, execution.id)
        if existing:
            existing.status = ComparisonStatus.PROCESSING
            existing.error_message = message
            existing.trace_id = execution.trace_id
            existing.retry_count = (existing.retry_count or 0) + 1
            await comparison_repo.update(session, existing)
            return

        pending = ComparisonResult(
            execution_id=execution.id,
            scenario_id=scenario_id,
            llm_model_id=execution.llm_model_id,
            trace_id=execution.trace_id,
            source_type=ComparisonSourceType.EXECUTION_AUTO,
            process_score=None,
            result_score=None,
            overall_passed=False,
            details_json=None,
            status=ComparisonStatus.PROCESSING,
            error_message=message,
            retry_count=1,
        )
        await comparison_repo.create(session, pending)

    # 查询并发批次状态，汇总完成、失败、运行中数量以及每路执行的基础信息。
    async def get_concurrent_execution_status(self, batch_id: str) -> dict[str, Any]:
        executions = await self.repo.get_by_batch_id(batch_id)
        total = len(executions)
        completed = sum(
            1 for execution in executions if execution.status in [ExecutionStatus.COMPLETED, ExecutionStatus.COMPLETED_WITH_MISMATCH]
        )
        failed = sum(1 for execution in executions if execution.status == ExecutionStatus.FAILED)
        running = sum(1 for execution in executions if execution.status == ExecutionStatus.RUNNING)

        execution_items = []
        for idx, execution in enumerate(executions):
            execution_items.append(
                {
                    "id": execution.id,
                    "call_index": idx + 1,
                    "status": execution.status,
                    "trace_id": execution.trace_id,
                    "original_request": execution.original_request,
                    "original_response": execution.original_response,
                    "started_at": execution.started_at.isoformat() if execution.started_at else None,
                    "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
                    "duration": (
                        execution.completed_at - execution.started_at
                    ).total_seconds() if execution.started_at and execution.completed_at else None,
                    "error_message": execution.error_message,
                    "user_session": execution.user_session,
                }
            )

        return {
            "batch_id": batch_id,
            "total": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "status": "completed" if total > 0 and completed + failed == total else "running",
            "executions": execution_items,
        }
