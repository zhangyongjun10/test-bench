"""执行服务"""

import uuid
import time
from datetime import datetime
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import BackgroundTasks
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

        # 触发异步执行
        background_tasks.add_task(self.run_execution, result.id)

        return result.id

    async def run_execution(self, execution_id: UUID) -> None:
        """后台执行：调用 Agent -> 拉 Trace -> 提取指标 -> 比对"""
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
            client = HTTPAgentClient(agent.base_url, api_key, timeout=settings.agent_timeout_seconds)

            execution.original_request = scenario.prompt
            response = await client.invoke(scenario.prompt, execution.trace_id)
            execution.original_response = response
            logger.info(f"Agent call completed: {execution_id}")

            # 4. 更新状态为 pulling_trace
            execution.status = ExecutionStatus.PULLING_TRACE
            await self.repo.update(execution)

            # 5. 拉取 Trace
            logger.info(f"Pulling trace: {execution.trace_id} for execution {execution_id}")
            trace_fetcher = TraceFetcherImpl()
            spans = await trace_fetcher.fetch_spans(execution.trace_id)
            logger.info(f"Pulled {len(spans)} spans for execution {execution_id}")

            # 6. 提取指标
            extractor = MetricExtractor()
            metrics = extractor.extract(spans)
            # TODO: 存储指标到 Prometheus
            logger.info(f"Metrics extracted for execution {execution_id}")

            # 7. 更新状态为 comparing
            execution.status = ExecutionStatus.COMPARING
            await self.repo.update(execution)

            # 8. 比对
            if scenario.compare_result and execution.original_response and scenario.baseline_result:
                from app.services.llm_service import LLMService
                llm_service = LLMService(self.session)
                llm_model = None
                if execution.llm_model_id:
                    llm_model = await llm_service.get_llm(execution.llm_model_id)
                else:
                    llm_model = await llm_service.get_default()

                if llm_model:
                    comparison = ComparisonService(llm_service.get_client(llm_model))
                    compare_result = await comparison.compare(
                        question=scenario.prompt,
                        actual=execution.original_response,
                        baseline=scenario.baseline_result
                    )
                    execution.comparison_score = compare_result.score
                    execution.comparison_passed = compare_result.passed
                    observe_comparison_score(compare_result.score)
                    logger.info(f"Comparison done: score={compare_result.score} passed={compare_result.passed}")

            # 9. 完成
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
    ) -> list[ExecutionJob]:
        """列出执行"""
        return await self.repo.list_all(agent_id, scenario_id, limit, offset)

    async def delete_execution(self, execution_id: UUID) -> bool:
        """删除执行"""
        execution = await self.repo.get_by_id(execution_id)
        if not execution:
            return False
        await self.repo.delete(execution_id)
        logger.info(f"Deleted execution: {execution_id}")
        return True
