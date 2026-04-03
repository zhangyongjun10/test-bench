"""执行服务"""

import uuid
import time
from datetime import datetime
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import BackgroundTasks
from app.core.db import AsyncSessionLocal
from app.domain.entities.execution import ExecutionJob, ExecutionStatus
from app.domain.entities.agent import Agent
from app.domain.entities.scenario import Scenario
from app.domain.entities.llm import LLMModel
from app.domain.entities.trace import Span, ExecutionMetrics
from app.domain.repositories.execution_repo import ExecutionRepository, SQLAlchemyExecutionRepository
from app.domain.repositories.agent_repo import SQLAlchemyAgentRepository
from app.domain.repositories.scenario_repo import SQLAlchemyScenarioRepository
from app.models.execution import CreateExecutionRequest
from app.core.encryption import encryption_service
from app.core.logger import logger
from app.core.metrics import (
    increment_executions_total,
    observe_execution_duration,
    observe_comparison_score
)
from app.config import settings
from app.clients.http_agent_client import HTTPAgentClient


class ExecutionService:
    def __init__(self, session: AsyncSession):
        self.repo: ExecutionRepository = SQLAlchemyExecutionRepository(session)
        self.agent_repo = SQLAlchemyAgentRepository(session)
        self.scenario_repo = SQLAlchemyScenarioRepository(session)
        self.session = session

    async def create_execution(self, request: CreateExecutionRequest, background_tasks: BackgroundTasks) -> UUID:
        """创建执行任务，触发异步执行"""
        # 校验参数
        agent = await self.agent_repo.get_by_id(request.agent_id)
        if not agent:
            raise ValueError(f"Agent {request.agent_id} not found")

        scenario = await self.scenario_repo.get_by_id(request.scenario_id)
        if not scenario:
            raise ValueError(f"Scenario {request.scenario_id} not found")

        # 创建任务
        execution = ExecutionJob(
            agent_id=request.agent_id,
            scenario_id=request.scenario_id,
            llm_model_id=request.llm_model_id,
            trace_id=str(uuid.uuid4()),
            status=ExecutionStatus.QUEUED
        )
        result = await self.repo.create(execution)
        logger.info(f"Created execution job: {result.id} trace_id={result.trace_id}")

        # 触发异步执行（用模块级函数，让后台任务自建独立 session）
        background_tasks.add_task(_run_execution_background, result.id)

        return result.id

    async def run_execution(self, execution_id: UUID) -> None:
        """后台执行：调用 Agent -> 拉 Trace -> 提取指标 -> 比对（使用 self.session）"""
        from app.services.trace_fetcher import TraceFetcherImpl
        from app.services.metric_extractor import MetricExtractor
        from app.services.comparison import ComparisonService

        start_time = time.time()
        execution = await self.repo.get_by_id(execution_id)
        if not execution:
            logger.error(f"Execution not found: {execution_id}")
            return

        try:
            # 1. 更新状态为 running
            execution.status = ExecutionStatus.RUNNING
            execution.started_at = datetime.utcnow()
            await self.repo.update(execution)

            # 2. 获取配置
            agent = await self.agent_repo.get_by_id(execution.agent_id)
            scenario = await self.scenario_repo.get_by_id(execution.scenario_id)

            # 3. 调用 Agent
            logger.info(f"Calling agent: {agent.id} for execution {execution_id}")
            api_key = encryption_service.decrypt(agent.api_key_encrypted)
            client = HTTPAgentClient(
                agent.base_url,
                api_key,
                timeout=settings.agent_timeout_seconds,
                user_session=agent.user_session
            )

            execution.original_request = scenario.prompt
            response_content, response_data = await client.invoke(scenario.prompt, execution.trace_id)
            execution.original_response = response_content
            logger.info(f"Agent call completed: {execution_id}")

            # 从 Agent 返回结果提取 id 字段作为 runId，解析得到真实 trace_id
            if response_data and isinstance(response_data, dict):
                logger.info(f"[DEBUG] Agent response_data keys: {list(response_data.keys())}")
                if 'id' in response_data:
                    run_id = str(response_data['id'])
                    logger.info(f"Got run_id from agent response: {run_id}")
                    # 根据 runId 从 opik.traces 查找真实 trace_id
                    trace_fetcher = TraceFetcherImpl(self.session)
                    real_trace_id = await trace_fetcher.get_trace_id_by_run_id(run_id)
                    logger.info(f"[DEBUG] get_trace_id_by_run_id result: real_trace_id = {real_trace_id}")
                    if real_trace_id:
                        logger.info(f"Resolved run_id {run_id} -> real trace_id {real_trace_id}")
                        execution.trace_id = real_trace_id
                    else:
                        logger.warning(f"Failed to find trace_id for run_id {run_id}")
                        execution.trace_id = run_id
                    logger.info(f"[DEBUG] After update, execution.trace_id = {execution.trace_id}")
                    await self.repo.update(execution)
                    logger.info(f"[DEBUG] Database updated")
                else:
                    logger.warning(f"No 'id' field in agent response, keys are: {list(response_data.keys())}")

            # 4. 更新状态为 pulling_trace
            execution.status = ExecutionStatus.PULLING_TRACE
            await self.repo.update(execution)

            # 5. 拉取 Trace（带重试，等待 Opik SDK 异步写入完成）
            logger.info(f"Pulling trace: {execution.trace_id} for execution {execution_id}")
            trace_fetcher = TraceFetcherImpl(self.session)
            spans = []
            _trace_retry_delays = [2, 4, 8, 15]  # 秒，累计最多等待 ~30s
            for _attempt, _delay in enumerate([0] + _trace_retry_delays):
                if _delay > 0:
                    import asyncio as _asyncio
                    logger.info(f"Trace not ready, waiting {_delay}s before retry ({_attempt}/{len(_trace_retry_delays)})...")
                    await _asyncio.sleep(_delay)
                spans = await trace_fetcher.fetch_spans(execution.trace_id)
                if spans:
                    break
            if not spans:
                logger.warning(f"No spans found for trace {execution.trace_id} after retries")
            logger.info(f"Pulled {len(spans)} spans for execution {execution_id}")

            # 6. 提取指标
            extractor = MetricExtractor()
            metrics = extractor.extract(spans)
            # TODO: 存储指标到 Prometheus
            logger.info(f"Metrics extracted for execution {execution_id}")

            # 7. 更新状态为 comparing
            execution.status = ExecutionStatus.COMPARING
            await self.repo.update(execution)

            # 8. 详细比对（新）
            overall_passed: Optional[bool] = None
            final_score: Optional[float] = None

            if scenario.compare_enabled and execution.llm_model_id:
                from app.services.llm_service import LLMService
                from app.domain.entities.comparison import ComparisonResult, ComparisonStatus
                from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository
                from app.services.comparison import ComparisonService

                try:
                    llm_service = LLMService(self.session)
                    llm_model = await llm_service.get_llm(execution.llm_model_id)

                    if llm_model:
                        # 创建比对服务（复用已拉取的 spans，不重复查 ClickHouse）
                        comparison_repo = SQLAlchemyComparisonRepository()
                        comparison_service = ComparisonService(
                            llm_service.get_client(llm_model),
                            comparison_repo
                        )

                        # 执行详细比对
                        comparison_result = await comparison_service.detailed_compare(
                            scenario=scenario,
                            execution=execution,
                            trace_spans=spans,
                        )

                        # 保存比对结果
                        await comparison_repo.create(self.session, comparison_result)
                        logger.info(f"Detailed comparison done: process_score={comparison_result.process_score} result_score={comparison_result.result_score} overall_passed={comparison_result.overall_passed}")

                        # 更新 execution 信息
                        if comparison_result.process_score is not None and comparison_result.result_score is not None:
                            final_score = (comparison_result.process_score + comparison_result.result_score) / 2
                        elif comparison_result.process_score is not None:
                            final_score = comparison_result.process_score
                        elif comparison_result.result_score is not None:
                            final_score = comparison_result.result_score
                        else:
                            final_score = None

                        execution.comparison_score = final_score
                        execution.comparison_passed = comparison_result.overall_passed
                        overall_passed = comparison_result.overall_passed

                        if final_score is not None:
                            observe_comparison_score(final_score / 100.0)
                except Exception as e:
                    # 比对过程出错，记录失败但不影响 execution 状态（执行已经成功完成）
                    logger.error(f"Detailed comparison failed for execution {execution_id}: {e}", exc_info=True)
                    from app.domain.repositories.comparison_repo import SQLAlchemyComparisonRepository
                    comparison_repo = SQLAlchemyComparisonRepository()
                    # 创建失败的比对记录
                    failed_comparison = ComparisonResult(
                        execution_id=execution.id,
                        scenario_id=scenario.id,
                        trace_id=execution.trace_id,
                        process_score=None,
                        result_score=None,
                        overall_passed=False,
                        details_json=None,
                        status=ComparisonStatus.FAILED,
                        error_message=str(e),
                        retry_count=0,
                    )
                    await comparison_repo.create(self.session, failed_comparison)
                    # execution 保持 COMPLETED，因为执行已经成功完成，只是比对失败
                    overall_passed = None
                    execution.comparison_score = None
                    execution.comparison_passed = None

            # 兼容原有简单比对
            elif scenario.compare_result and execution.original_response and scenario.baseline_result and execution.llm_model_id:
                from app.services.llm_service import LLMService
                llm_service = LLMService(self.session)
                llm_model = await llm_service.get_llm(execution.llm_model_id)

                if llm_model:
                    comparison = ComparisonService(llm_service.get_client(llm_model), None)
                    compare_result = await comparison.compare(
                        question=scenario.prompt,
                        actual=execution.original_response,
                        baseline=scenario.baseline_result
                    )
                    execution.comparison_score = compare_result.score * 100
                    execution.comparison_passed = compare_result.passed
                    overall_passed = compare_result.passed
                    observe_comparison_score(compare_result.score)
                    logger.info(f"Legacy comparison done: score={compare_result.score} passed={compare_result.passed}")

            # 9. 完成，设置最终状态
            if overall_passed is False:
                execution.status = ExecutionStatus.COMPLETED_WITH_MISMATCH
            else:
                execution.status = ExecutionStatus.COMPLETED
            execution.completed_at = datetime.utcnow()
            await self.repo.update(execution)

            duration = time.time() - start_time
            increment_executions_total(status=ExecutionStatus.COMPLETED)
            observe_execution_duration(duration)
            logger.info(f"Execution completed: {execution_id} duration={duration:.2f}s")

        except Exception as e:
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(e)
            execution.completed_at = datetime.utcnow()
            await self.repo.update(execution)

            duration = time.time() - start_time
            increment_executions_total(status=ExecutionStatus.FAILED)
            observe_execution_duration(duration)
            logger.error(f"Execution failed: {execution_id} error={e}")

    async def get_execution(self, execution_id: UUID) -> Optional[ExecutionJob]:
        """获取执行"""
        return await self.repo.get_by_id(execution_id)

    async def list_executions(
        self,
        agent_id: Optional[UUID] = None,
        scenario_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[int, list[ExecutionJob]]:
        """列出执行，返回 (total_count, items)"""
        return await self.repo.list_all(agent_id, scenario_id, limit, offset)

    async def delete_execution(self, execution_id: UUID) -> bool:
        """删除执行"""
        execution = await self.repo.get_by_id(execution_id)
        if not execution:
            return False
        await self.repo.delete(execution_id)
        logger.info(f"Deleted execution: {execution_id}")
        return True


async def _run_execution_background(execution_id: UUID) -> None:
    """后台任务入口：创建独立 Session，不依赖 HTTP 请求的 Session 生命周期"""
    async with AsyncSessionLocal() as session:
        service = ExecutionService(session)
        await service.run_execution(execution_id)
