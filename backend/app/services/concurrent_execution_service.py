"""OpenClaw 并发执行服务。"""

import asyncio
import inspect
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
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
from app.domain.entities.comparison import ComparisonResult, ComparisonSourceType, ComparisonStatus
from app.domain.entities.execution import ExecutionJob, ExecutionRunSource, ExecutionStatus
from app.domain.entities.execution_batch import ExecutionBatch, ExecutionBatchStatus
from app.domain.repositories.agent_repo import SQLAlchemyAgentRepository
from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository
from app.domain.repositories.execution_batch_repo import SQLAlchemyExecutionBatchRepository
from app.domain.repositories.execution_repo import ExecutionRepository, SQLAlchemyExecutionRepository
from app.domain.repositories.scenario_repo import SQLAlchemyScenarioRepository
from app.services.comparison import ComparisonService
from app.services.execution_service import count_openai_llm_spans, is_trace_ready_for_comparison
from app.services.llm_service import LLMService
from app.services.trace_fetcher import TraceFetcherImpl


# 并发执行数据库访问信号量；只限制数据库读写区，不限制真正下发到 OpenClaw 的 HTTP 并发。
DB_OPERATION_SEMAPHORE = asyncio.Semaphore(settings.concurrent_execution_db_concurrency)


# 并发执行所需的 Agent 配置快照；脱离 SQLAlchemy Session 后传递，避免后台长任务占用数据库连接。
@dataclass(frozen=True)
class AgentExecutionConfig:
    # Agent 主键，用于创建 execution 记录时保持归属关系。
    id: UUID
    # Agent HTTP 地址，用于构建 OpenClaw 兼容调用客户端。
    base_url: str
    # Agent 加密后的 API Key，只在构建 HTTP 客户端时解密。
    api_key_encrypted: str


# 已完成数据库准备的并发执行调用；所有记录准备完成后再统一启动 OpenClaw HTTP。
@dataclass(frozen=True)
class PreparedExecutionCall:
    # 已落库的 execution，后续 HTTP 结果会回写到该记录。
    execution: ExecutionJob
    # 当前并发批次中的调用序号，用于日志和前端批次状态展示。
    call_index: int


# 并发单路执行结果状态枚举；所有子任务都必须落入这些状态之一，避免异常被静默吞掉。
class ConcurrentCallStatus:
    PREPARED_FAILED = "prepared_failed"
    START_MARK_FAILED = "start_mark_failed"
    AGENT_FAILED = "agent_failed"
    COMPARISON_DEFERRED = "comparison_deferred"
    COMPARISON_FAILED = "comparison_failed"
    COMPLETED = "completed"
    COMPLETED_WITH_MISMATCH = "completed_with_mismatch"


# 并发单路执行结果；用于后台批次汇总和日志观测，execution 创建前失败时允许 execution_id 为空。
@dataclass(frozen=True)
class ConcurrentCallResult:
    # 当前结果关联的 execution ID；准备阶段创建 execution 前失败时为空。
    execution_id: UUID | None
    # 当前并发批次中的调用序号，用于定位是哪一路并发失败。
    call_index: int
    # 单路执行结果状态，只能取 ConcurrentCallStatus 中定义的值。
    status: str
    # 单路失败原因；成功或延迟比对时可以为空。
    error_message: str | None = None


# 比对运行结果状态枚举；区分已完成、已安排延迟、跳过和失败，避免主流程误标 completed。
class ComparisonRunState:
    COMPLETED = "completed"
    DEFERRED = "deferred"
    SKIPPED = "skipped"
    FAILED = "failed"


# 比对运行结果；主流程按 state 明确更新 execution 终态或保留 comparing 等待补偿。
@dataclass(frozen=True)
class ComparisonRunOutcome:
    # 比对运行状态，决定主执行是否能进入 completed/completed_with_mismatch/failed。
    state: str
    # 比对是否通过；只有 state=completed 时才有业务含义。
    passed: bool | None = None
    # 比对失败或延迟说明，会写入 comparison/error_message 供页面展示。
    error_message: str | None = None


# 并发执行服务，负责为同一个场景创建多条隔离 user_session 的 Agent 执行记录。
class ConcurrentExecutionService:
    # 首次拉取 Trace 的最大重试次数，避免并发执行刚结束时 Opik span 尚未完整写入。
    TRACE_FETCH_RETRIES = 5
    # 首次拉取 Trace 的重试间隔秒数，配合 ready 判断等待最终 OpenAI 文本 span。
    TRACE_FETCH_RETRY_INTERVAL_SECONDS = 2.0
    # 根据 run_id 反查真实 trace_id 的最大重试次数，处理 OpenClaw 响应 ID 与 Opik trace_id 延迟关联。
    TRACE_ID_RESOLUTION_RETRIES = 5
    # 根据 run_id 反查真实 trace_id 的重试间隔秒数。
    TRACE_ID_RESOLUTION_RETRY_INTERVAL_SECONDS = 2.0
    # 延迟比对最大重试次数，用于首次并发执行结束后 Trace 仍未达到可比对状态的场景。
    DEFERRED_COMPARISON_RETRIES = 12
    # 延迟比对重试间隔秒数，避免过于频繁查询 ClickHouse。
    DEFERRED_COMPARISON_RETRY_INTERVAL_SECONDS = 5.0

    # 初始化并发执行服务，所有并发请求统一按多路独立 execution、独立 session 执行。
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo: ExecutionRepository = SQLAlchemyExecutionRepository(session)
        self.batch_repo = SQLAlchemyExecutionBatchRepository(session)

    # 构建 Agent HTTP 客户端；正式执行超时使用全局 Agent 超时配置。
    def _build_client(self, agent: AgentExecutionConfig) -> HTTPAgentClient:
        api_key = encryption_service.decrypt(agent.api_key_encrypted)
        return HTTPAgentClient(
            agent.base_url,
            api_key,
            timeout=settings.agent_timeout_seconds,
            verify_ssl=False,
        )

    # 限制并发执行链路中的数据库访问；外部 Agent HTTP、sleep、LLM 比对不进入该临界区。
    @asynccontextmanager
    async def _limit_db_operation(self):
        async with DB_OPERATION_SEMAPHORE:
            yield

    # 释放仓储持有的数据库连接；生产 AsyncSession 会归还连接池，测试假对象没有 close 时跳过。
    async def _release_repo_session(self, repo: ExecutionRepository) -> None:
        close = getattr(repo.session, "close", None)
        if not close:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    # 创建并发执行批次并注册后台任务；批次先落库，保证准备阶段全失败也能查询到状态。
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
        if concurrency > settings.concurrent_execution_max_concurrency:
            raise ValueError(f"并发数超过系统上限，当前上限为 {settings.concurrent_execution_max_concurrency}")
        if not scenario_id:
            raise ValueError("scenario_id is required")
        if not agent_id:
            raise ValueError("agent_id is required")

        batch_id = str(uuid.uuid4())
        batch = ExecutionBatch(
            id=batch_id,
            requested_concurrency=concurrency,
            status=ExecutionBatchStatus.QUEUED,
        )
        async with self._limit_db_operation():
            await self.batch_repo.create(batch)

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

    # 后台运行并发执行批次；读取 Agent 后释放数据库连接，再进入批量准备和真实 Agent 并发调用。
    async def run_concurrent_execution(
        self,
        batch_id: str,
        input_text: str,
        concurrency: int,
        scenario_id: UUID,
        llm_model_id: UUID | None,
        agent_id: UUID,
    ) -> None:
        try:
            await self._update_batch_fields(batch_id, status=ExecutionBatchStatus.PREPARING)
            async with AsyncSessionLocal() as session:
                agent_repo = SQLAlchemyAgentRepository(session)
                async with self._limit_db_operation():
                    agent = await agent_repo.get_by_id(agent_id)
                if not agent:
                    await self._mark_batch_failed(batch_id, f"Agent {agent_id} 不存在")
                    return
                agent_config = AgentExecutionConfig(
                    id=agent.id,
                    base_url=agent.base_url,
                    api_key_encrypted=agent.api_key_encrypted,
                )
            await self._run_concurrent_calls(batch_id, input_text, concurrency, scenario_id, llm_model_id, agent_config)
        except Exception as exc:
            logger.error("Concurrent execution failed: %s error=%s", batch_id, exc, exc_info=True)
            await self._mark_batch_failed(batch_id, f"并发批次执行失败：{exc}")

    # 统一执行并发调用；先按 DB 限流准备所有 execution，再一次性启动 OpenClaw HTTP 以保证真实 Agent 并发。
    async def _run_concurrent_calls(
        self,
        batch_id: str,
        input_text: str,
        concurrency: int,
        scenario_id: UUID,
        llm_model_id: UUID | None,
        agent: AgentExecutionConfig,
    ) -> None:
        async def prepare_with_own_session(call_index: int) -> PreparedExecutionCall | ConcurrentCallResult:
            current_task = asyncio.current_task()
            if current_task:
                current_task.set_name(f"concurrent:{batch_id}:prepare:{call_index}")
            try:
                async with AsyncSessionLocal() as session:
                    local_repo = SQLAlchemyExecutionRepository(session)
                    return await self._prepare_single_call(
                        batch_id=batch_id,
                        input_text=input_text,
                        scenario_id=scenario_id,
                        llm_model_id=llm_model_id,
                        agent=agent,
                        repo=local_repo,
                        call_index=call_index,
                    )
            except Exception as exc:
                logger.error("Concurrent execution prepare failed: %s", exc, exc_info=True)
                return ConcurrentCallResult(
                    execution_id=None,
                    call_index=call_index,
                    status=ConcurrentCallStatus.PREPARED_FAILED,
                    error_message=str(exc),
                )

        prepare_results = await asyncio.gather(
            *(asyncio.create_task(prepare_with_own_session(i + 1)) for i in range(concurrency)),
        )
        prepared_calls = [result for result in prepare_results if isinstance(result, PreparedExecutionCall)]
        prepare_failed_count = len(prepare_results) - len(prepared_calls)
        await self._update_batch_fields(
            batch_id,
            prepared_count=len(prepared_calls),
            prepare_failed_count=prepare_failed_count,
        )

        agent_started_at = datetime.now(UTC)
        started_calls, start_mark_failed_count = await self._mark_prepared_calls_started(prepared_calls, agent_started_at)
        await self._update_batch_fields(
            batch_id,
            started_count=len(started_calls),
            start_mark_failed_count=start_mark_failed_count,
            agent_started_at=agent_started_at,
            status=ExecutionBatchStatus.RUNNING if started_calls else ExecutionBatchStatus.COMPLETED_WITH_FAILURES,
        )
        if not started_calls:
            await self._refresh_batch_status(batch_id)
            return

        async def execute_with_own_session(prepared_call: PreparedExecutionCall) -> ConcurrentCallResult:
            current_task = asyncio.current_task()
            if current_task:
                current_task.set_name(f"concurrent:{batch_id}:call:{prepared_call.call_index}")
            try:
                async with AsyncSessionLocal() as session:
                    local_repo = SQLAlchemyExecutionRepository(session)
                    return await self._execute_single_call(
                        input_text=input_text,
                        llm_model_id=llm_model_id,
                        agent=agent,
                        repo=local_repo,
                        prepared_call=prepared_call,
                    )
            except Exception as exc:
                logger.error("Concurrent execution outer call failed: %s", exc, exc_info=True)
                await self._mark_execution_failed(prepared_call.execution.id, f"并发执行外层异常：{exc}")
                return ConcurrentCallResult(
                    execution_id=prepared_call.execution.id,
                    call_index=prepared_call.call_index,
                    status=ConcurrentCallStatus.AGENT_FAILED,
                    error_message=str(exc),
                )

        await asyncio.gather(
            *(asyncio.create_task(execute_with_own_session(prepared_call)) for prepared_call in started_calls),
        )
        await self._refresh_batch_status(batch_id)

    # 准备单路并发执行记录；该阶段只做数据库写入，不调用 OpenClaw。
    async def _prepare_single_call(
        self,
        *,
        batch_id: str,
        input_text: str,
        scenario_id: UUID,
        llm_model_id: UUID | None,
        agent: AgentExecutionConfig,
        repo: ExecutionRepository,
        call_index: int,
    ) -> PreparedExecutionCall:
        execution_id = uuid.uuid4()
        execution = ExecutionJob(
            id=execution_id,
            agent_id=agent.id,
            scenario_id=scenario_id,
            llm_model_id=llm_model_id,
            user_session=f"exec_{execution_id.hex}",
            run_source=ExecutionRunSource.NORMAL,
            parent_execution_id=None,
            request_snapshot_json=None,
            trace_id=str(uuid.uuid4()),
            status=ExecutionStatus.QUEUED,
            batch_id=batch_id,
            original_request=input_text,
        )
        async with self._limit_db_operation():
            execution = await repo.create(execution)
        await self._release_repo_session(repo)
        return PreparedExecutionCall(execution=execution, call_index=call_index)

    # 将已准备好的 execution 统一切换为 running，并把页面展示时间统一成真正放闸调用 Agent 的时间。
    async def _mark_prepared_calls_started(
        self,
        prepared_calls: list[PreparedExecutionCall],
        agent_started_at: datetime,
    ) -> tuple[list[PreparedExecutionCall], int]:
        async def mark_one(prepared_call: PreparedExecutionCall) -> PreparedExecutionCall | ConcurrentCallResult:
            async with AsyncSessionLocal() as session:
                repo = SQLAlchemyExecutionRepository(session)
                execution = prepared_call.execution
                try:
                    execution.status = ExecutionStatus.RUNNING
                    execution.created_at = agent_started_at
                    execution.started_at = agent_started_at
                    execution.updated_at = agent_started_at
                    async with self._limit_db_operation():
                        await repo.update(execution)
                    await self._release_repo_session(repo)
                    return prepared_call
                except Exception as exc:
                    logger.error("Concurrent execution start mark failed: %s", exc, exc_info=True)
                    execution.status = ExecutionStatus.FAILED
                    execution.error_message = f"并发执行启动时间写入失败：{exc}"
                    execution.completed_at = datetime.now(UTC)
                    try:
                        async with self._limit_db_operation():
                            await repo.update(execution)
                    except Exception:
                        logger.error("Failed to mark prepared execution as failed: %s", execution.id, exc_info=True)
                    return ConcurrentCallResult(
                        execution_id=execution.id,
                        call_index=prepared_call.call_index,
                        status=ConcurrentCallStatus.START_MARK_FAILED,
                        error_message=str(exc),
                    )

        marked_results = await asyncio.gather(
            *(asyncio.create_task(mark_one(prepared_call)) for prepared_call in prepared_calls),
        )
        started_calls = [result for result in marked_results if isinstance(result, PreparedExecutionCall)]
        start_mark_failed_count = len(marked_results) - len(started_calls)
        return started_calls, start_mark_failed_count

    # 执行单路并发调用并回写结果；OpenClaw HTTP 调用不受 DB 信号量限制。
    async def _execute_single_call(
        self,
        *,
        input_text: str,
        llm_model_id: UUID | None,
        agent: AgentExecutionConfig,
        repo: ExecutionRepository,
        prepared_call: PreparedExecutionCall,
    ) -> ConcurrentCallResult:
        start_time = time.time()
        execution = prepared_call.execution
        call_index = prepared_call.call_index

        try:
            client = self._build_client(agent)
            response_content, response_data = await client.invoke(
                input_text,
                execution.trace_id,
                user_session=execution.user_session,
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
                execution.trace_id = real_trace_id or execution.trace_id
                async with self._limit_db_operation():
                    await repo.update(execution)
                await self._release_repo_session(repo)

            comparison_outcome = ComparisonRunOutcome(state=ComparisonRunState.SKIPPED)
            if llm_model_id:
                execution.status = ExecutionStatus.PULLING_TRACE
                async with self._limit_db_operation():
                    await repo.update(execution)
                await self._release_repo_session(repo)
                comparison_outcome = await self._run_comparison(
                    repo.session,
                    execution,
                    execution.scenario_id,
                    llm_model_id,
                )

            if comparison_outcome.state == ComparisonRunState.DEFERRED:
                execution.status = ExecutionStatus.COMPARING
                async with self._limit_db_operation():
                    await repo.update(execution)
                return ConcurrentCallResult(execution.id, call_index, ConcurrentCallStatus.COMPARISON_DEFERRED)

            if comparison_outcome.state == ComparisonRunState.FAILED:
                message = comparison_outcome.error_message or "并发执行比对失败"
                await self._mark_execution_failed_with_repo(repo, execution, message)
                return ConcurrentCallResult(execution.id, call_index, ConcurrentCallStatus.COMPARISON_FAILED, message)

            execution.status = (
                ExecutionStatus.COMPLETED_WITH_MISMATCH
                if comparison_outcome.state == ComparisonRunState.COMPLETED and comparison_outcome.passed is False
                else ExecutionStatus.COMPLETED
            )
            execution.completed_at = datetime.now(UTC)
            async with self._limit_db_operation():
                await repo.update(execution)

            duration = time.time() - start_time
            increment_executions_total(status=ExecutionStatus.COMPLETED)
            observe_execution_duration(duration)
            result_status = (
                ConcurrentCallStatus.COMPLETED_WITH_MISMATCH
                if execution.status == ExecutionStatus.COMPLETED_WITH_MISMATCH
                else ConcurrentCallStatus.COMPLETED
            )
            return ConcurrentCallResult(execution.id, call_index, result_status)
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            await self._mark_execution_failed_with_repo(repo, execution, message)
            duration = time.time() - start_time
            increment_executions_total(status=ExecutionStatus.FAILED)
            observe_execution_duration(duration)
            logger.error("Concurrent execution call failed: %s", exc, exc_info=True)
            return ConcurrentCallResult(execution.id, call_index, ConcurrentCallStatus.AGENT_FAILED, message)

    # 为并发执行结果触发比对；Trace 未就绪时写入处理中比对记录并返回 deferred。
    async def _run_comparison(
        self,
        session: AsyncSession,
        execution: ExecutionJob,
        scenario_id: UUID,
        llm_model_id: UUID,
        spans: Optional[list] = None,
    ) -> ComparisonRunOutcome:
        scenario_repo = SQLAlchemyScenarioRepository(session)
        async with self._limit_db_operation():
            scenario = await scenario_repo.get_by_id(scenario_id)
        if not scenario:
            return ComparisonRunOutcome(ComparisonRunState.FAILED, error_message=f"测试场景 {scenario_id} 不存在")
        if not scenario.compare_enabled:
            return ComparisonRunOutcome(ComparisonRunState.SKIPPED)

        llm_service = LLMService(session)
        async with self._limit_db_operation():
            llm_model = await llm_service.get_llm(llm_model_id)
        if not llm_model:
            message = f"比对模型 {llm_model_id} 不存在"
            logger.warning("%s for execution %s", message, execution.id)
            return ComparisonRunOutcome(ComparisonRunState.FAILED, error_message=message)
        await session.close()

        expected_min_llm_count = scenario.llm_count_min or 0
        if spans is None:
            spans = await self._fetch_spans_with_retry(
                session,
                execution,
                expected_min_llm_count=expected_min_llm_count,
            )
        if not spans or not is_trace_ready_for_comparison(spans, expected_min_llm_count):
            async with self._limit_db_operation():
                await self._upsert_pending_comparison(
                    session,
                    execution,
                    scenario_id,
                    "Trace 尚未出现最终 OpenAI 文本输出，已安排延迟比对。",
                )
            self._schedule_deferred_comparison(execution.id, scenario_id, llm_model_id)
            return ComparisonRunOutcome(ComparisonRunState.DEFERRED, error_message="Trace 尚未出现最终 OpenAI 文本输出，已安排延迟比对。")

        execution.status = ExecutionStatus.COMPARING
        async with self._limit_db_operation():
            await SQLAlchemyExecutionRepository(session).update(execution)

        comparison_repo = SQLAlchemyComparisonRepository()
        comparison_service = ComparisonService(llm_service.get_client(llm_model), comparison_repo)
        await session.close()
        comparison_result = await comparison_service.detailed_compare(
            scenario=scenario,
            execution=execution,
            trace_spans=spans,
            llm_model=llm_model,
        )
        comparison_result.source_type = ComparisonSourceType.EXECUTION_AUTO
        async with self._limit_db_operation():
            await comparison_repo.create(session, comparison_result)

        execution.comparison_score = None
        execution.comparison_passed = comparison_result.overall_passed
        async with self._limit_db_operation():
            await SQLAlchemyExecutionRepository(session).update(execution)
        return ComparisonRunOutcome(ComparisonRunState.COMPLETED, passed=comparison_result.overall_passed)

    # 安排延迟比对任务，避免 Trace 异步落库慢导致当前批次立即误判。
    def _schedule_deferred_comparison(self, execution_id: UUID, scenario_id: UUID, llm_model_id: UUID) -> None:
        asyncio.create_task(
            self._run_deferred_comparison(execution_id, scenario_id, llm_model_id),
            name=f"comparison:{execution_id}",
        )

    # 执行延迟比对任务；所有可达出口都必须写入终态，避免卡在 comparing/processing。
    async def _run_deferred_comparison(self, execution_id: UUID, scenario_id: UUID, llm_model_id: UUID) -> None:
        async with AsyncSessionLocal() as session:
            execution_repo = SQLAlchemyExecutionRepository(session)
            async with self._limit_db_operation():
                execution = await execution_repo.get_by_id(execution_id)
            if not execution:
                return

            try:
                spans = await self._fetch_spans_with_retry(
                    session,
                    execution,
                    retries=self.DEFERRED_COMPARISON_RETRIES,
                    interval_seconds=self.DEFERRED_COMPARISON_RETRY_INTERVAL_SECONDS,
                    expected_min_llm_count=0,
                    return_last_unready=True,
                )
                if not spans:
                    await self._mark_deferred_comparison_failed(
                        session,
                        execution_repo,
                        execution,
                        scenario_id,
                        llm_model_id,
                        "多次重试后仍未找到 Trace spans",
                    )
                    await self._refresh_batch_status_if_needed(execution)
                    return
                if not is_trace_ready_for_comparison(spans, 0):
                    await self._mark_deferred_comparison_failed(
                        session,
                        execution_repo,
                        execution,
                        scenario_id,
                        llm_model_id,
                        "Trace 已存在但长时间未出现最终 OpenAI 文本输出",
                    )
                    await self._refresh_batch_status_if_needed(execution)
                    return

                comparison_outcome = await self._run_comparison(
                    session,
                    execution,
                    scenario_id,
                    llm_model_id,
                    spans=spans,
                )
                if comparison_outcome.state == ComparisonRunState.FAILED:
                    await self._mark_deferred_comparison_failed(
                        session,
                        execution_repo,
                        execution,
                        scenario_id,
                        llm_model_id,
                        comparison_outcome.error_message or "多次重试后比对仍未完成",
                    )
                    await self._refresh_batch_status_if_needed(execution)
                    return

                async with self._limit_db_operation():
                    execution = await execution_repo.get_by_id(execution_id)
                if not execution:
                    return
                execution.status = (
                    ExecutionStatus.COMPLETED_WITH_MISMATCH
                    if comparison_outcome.state == ComparisonRunState.COMPLETED and comparison_outcome.passed is False
                    else ExecutionStatus.COMPLETED
                )
                execution.completed_at = datetime.now(UTC)
                async with self._limit_db_operation():
                    await execution_repo.update(execution)
                await self._refresh_batch_status_if_needed(execution)
            except Exception as exc:
                logger.error("Deferred comparison failed for execution %s: %s", execution_id, exc, exc_info=True)
                async with self._limit_db_operation():
                    execution = await execution_repo.get_by_id(execution_id)
                if not execution:
                    return
                await self._mark_deferred_comparison_failed(
                    session,
                    execution_repo,
                    execution,
                    scenario_id,
                    llm_model_id,
                    f"自动延迟比对失败：{exc}",
                )
                await self._refresh_batch_status_if_needed(execution)

    # 将自动延迟比对失败收口到终态，避免 execution 或 comparison 长时间停留在 comparing/processing。
    async def _mark_deferred_comparison_failed(
        self,
        session: AsyncSession,
        execution_repo: SQLAlchemyExecutionRepository,
        execution: ExecutionJob,
        scenario_id: UUID,
        llm_model_id: UUID,
        message: str,
    ) -> None:
        logger.warning("Deferred comparison failed for execution %s: %s", execution.id, message)
        execution.status = ExecutionStatus.FAILED
        execution.error_message = message
        execution.completed_at = datetime.now(UTC)
        async with self._limit_db_operation():
            await execution_repo.update(execution)

        comparison_repo = SQLAlchemyComparisonRepository()
        async with self._limit_db_operation():
            existing = await comparison_repo.get_by_execution_id(session, execution.id)
        if existing:
            existing.status = ComparisonStatus.FAILED
            existing.error_message = message
            existing.trace_id = execution.trace_id
            existing.overall_passed = False
            existing.completed_at = datetime.now(UTC)
            async with self._limit_db_operation():
                await comparison_repo.update(session, existing)
            return

        failed_comparison = ComparisonResult(
            execution_id=execution.id,
            scenario_id=scenario_id,
            llm_model_id=llm_model_id,
            trace_id=execution.trace_id,
            source_type=ComparisonSourceType.EXECUTION_AUTO,
            process_score=None,
            result_score=None,
            overall_passed=False,
            details_json=None,
            status=ComparisonStatus.FAILED,
            error_message=message,
            retry_count=0,
            completed_at=datetime.now(UTC),
        )
        async with self._limit_db_operation():
            await comparison_repo.create(session, failed_comparison)

    # 带重试拉取执行 Trace；可选择在超时后返回最后一次未就绪 spans，用于区分无 Trace 和 Trace 未完成。
    async def _fetch_spans_with_retry(
        self,
        session: AsyncSession,
        execution: ExecutionJob,
        retries: Optional[int] = None,
        interval_seconds: Optional[float] = None,
        expected_min_llm_count: int = 0,
        return_last_unready: bool = False,
    ) -> list:
        trace_fetcher = TraceFetcherImpl(session)
        retry_count = self.TRACE_FETCH_RETRIES if retries is None else retries
        interval = self.TRACE_FETCH_RETRY_INTERVAL_SECONDS if interval_seconds is None else interval_seconds
        last_spans: list = []
        for attempt in range(1, retry_count + 1):
            async with self._limit_db_operation():
                spans = await trace_fetcher.fetch_spans(execution.trace_id)
            await session.close()
            if spans and is_trace_ready_for_comparison(spans, expected_min_llm_count):
                return spans
            if spans:
                last_spans = spans
                logger.info(
                    "Concurrent trace has %s spans and %s OpenAI LLM spans, but comparison is not ready yet for execution %s",
                    len(spans),
                    count_openai_llm_spans(spans),
                    execution.id,
                )
            if attempt < retry_count:
                await asyncio.sleep(interval)
        return last_spans if return_last_unready else []

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
            async with self._limit_db_operation():
                real_trace_id = await trace_fetcher.get_trace_id_by_run_id(run_id)
            await session.close()
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

    # 使用已有仓储将 execution 标记为失败；用于单路执行已持有 repo 的异常收口。
    async def _mark_execution_failed_with_repo(
        self,
        repo: ExecutionRepository,
        execution: ExecutionJob,
        message: str,
    ) -> None:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = message
        execution.completed_at = datetime.now(UTC)
        try:
            async with self._limit_db_operation():
                await repo.update(execution)
        except Exception:
            logger.error("Failed to mark execution as failed: %s", execution.id, exc_info=True)

    # 使用独立 Session 将 execution 标记为失败；用于外层异常已经脱离原 repo 的场景。
    async def _mark_execution_failed(self, execution_id: UUID, message: str) -> None:
        async with AsyncSessionLocal() as session:
            repo = SQLAlchemyExecutionRepository(session)
            async with self._limit_db_operation():
                execution = await repo.get_by_id(execution_id)
            if not execution:
                return
            await self._mark_execution_failed_with_repo(repo, execution, message)

    # 更新批次字段；所有批次状态修改统一经过该方法，避免多个后台任务重复写散落逻辑。
    async def _update_batch_fields(self, batch_id: str, **fields: Any) -> None:
        async with AsyncSessionLocal() as session:
            batch_repo = SQLAlchemyExecutionBatchRepository(session)
            async with self._limit_db_operation():
                batch = await batch_repo.get_by_id(batch_id)
            if not batch:
                return
            for key, value in fields.items():
                setattr(batch, key, value)
            batch.updated_at = datetime.now(UTC)
            async with self._limit_db_operation():
                await batch_repo.update(batch)

    # 将批次标记为失败；用于 Agent 不存在、批次级初始化失败等没有单路 execution 可承载的异常。
    async def _mark_batch_failed(self, batch_id: str, message: str) -> None:
        await self._update_batch_fields(
            batch_id,
            status=ExecutionBatchStatus.FAILED,
            error_message=message,
        )

    # 如果 execution 属于并发批次，则刷新批次聚合状态。
    async def _refresh_batch_status_if_needed(self, execution: ExecutionJob) -> None:
        if execution.batch_id:
            await self._refresh_batch_status(execution.batch_id)

    # 按 execution 明细和批次失败计数刷新批次聚合状态。
    async def _refresh_batch_status(self, batch_id: str) -> None:
        async with AsyncSessionLocal() as session:
            execution_repo = SQLAlchemyExecutionRepository(session)
            batch_repo = SQLAlchemyExecutionBatchRepository(session)
            async with self._limit_db_operation():
                executions = await execution_repo.get_by_batch_id(batch_id)
                batch = await batch_repo.get_by_id(batch_id)
            if not batch:
                return

            counts = self._count_execution_statuses(executions)
            running_count = counts["queued"] + counts["running"] + counts["pulling_trace"] + counts["comparing"]
            failure_count = counts["failed"] + (batch.prepare_failed_count or 0) + (batch.start_mark_failed_count or 0)
            if running_count > 0:
                batch.status = ExecutionBatchStatus.RUNNING
            elif failure_count > 0:
                batch.status = ExecutionBatchStatus.COMPLETED_WITH_FAILURES
            elif executions:
                batch.status = ExecutionBatchStatus.COMPLETED
            elif batch.status not in (ExecutionBatchStatus.FAILED, ExecutionBatchStatus.COMPLETED_WITH_FAILURES):
                batch.status = ExecutionBatchStatus.COMPLETED
            batch.updated_at = datetime.now(UTC)
            async with self._limit_db_operation():
                await batch_repo.update(batch)

    # 统计批次内各 execution 状态；queued/running/pulling_trace/comparing 都会被视为非终态。
    @staticmethod
    def _count_execution_statuses(executions: list[ExecutionJob]) -> dict[str, int]:
        return {
            "queued": sum(1 for item in executions if item.status == ExecutionStatus.QUEUED),
            "running": sum(1 for item in executions if item.status == ExecutionStatus.RUNNING),
            "pulling_trace": sum(1 for item in executions if item.status == ExecutionStatus.PULLING_TRACE),
            "comparing": sum(1 for item in executions if item.status == ExecutionStatus.COMPARING),
            "completed": sum(1 for item in executions if item.status == ExecutionStatus.COMPLETED),
            "completed_with_mismatch": sum(1 for item in executions if item.status == ExecutionStatus.COMPLETED_WITH_MISMATCH),
            "failed": sum(1 for item in executions if item.status == ExecutionStatus.FAILED),
        }

    # 查询并发批次状态，汇总完成、失败、运行中数量以及每路执行的基础信息。
    async def get_concurrent_execution_status(self, batch_id: str) -> dict[str, Any]:
        async with self._limit_db_operation():
            executions = await self.repo.get_by_batch_id(batch_id)
            batch = await self.batch_repo.get_by_id(batch_id)

        total = len(executions)
        if not batch and total == 0:
            return {
                "batch_id": batch_id,
                "total": 0,
                "aggregate_status": "not_found",
                "status": "not_found",
                "executions": [],
            }

        counts = self._count_execution_statuses(executions)
        running_count = counts["queued"] + counts["running"] + counts["pulling_trace"] + counts["comparing"]
        failed_total = counts["failed"] + ((batch.prepare_failed_count if batch else 0) or 0) + ((batch.start_mark_failed_count if batch else 0) or 0)
        if running_count > 0 or (batch and batch.status in [ExecutionBatchStatus.QUEUED, ExecutionBatchStatus.PREPARING, ExecutionBatchStatus.RUNNING]):
            aggregate_status = "running"
        elif failed_total > 0 or (batch and batch.status in [ExecutionBatchStatus.FAILED, ExecutionBatchStatus.COMPLETED_WITH_FAILURES]):
            aggregate_status = "completed_with_failures"
        else:
            aggregate_status = "completed"

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
            "requested_concurrency": batch.requested_concurrency if batch else total,
            "prepared_count": batch.prepared_count if batch else total,
            "started_count": batch.started_count if batch else total,
            "prepare_failed_count": batch.prepare_failed_count if batch else 0,
            "start_mark_failed_count": batch.start_mark_failed_count if batch else 0,
            "queued": counts["queued"],
            "running": running_count,
            "running_execution_count": counts["running"],
            "pulling_trace": counts["pulling_trace"],
            "comparing": counts["comparing"],
            "completed": counts["completed"],
            "completed_with_mismatch": counts["completed_with_mismatch"],
            "failed": counts["failed"],
            "aggregate_status": aggregate_status,
            "status": aggregate_status,
            "error_message": batch.error_message if batch else None,
            "agent_started_at": batch.agent_started_at.isoformat() if batch and batch.agent_started_at else None,
            "executions": execution_items,
        }
