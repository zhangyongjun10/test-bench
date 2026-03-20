"""Trace 拉取服务"""

from abc import ABC, abstractmethod
from typing import List
from uuid import UUID
import time
from app.domain.entities.trace import Span, SpanMetrics
from app.domain.repositories.execution_repo import SQLAlchemyExecutionRepository
from app.clients.clickhouse_client import ClickHouseClient
from app.core.logger import logger
from app.core.metrics import observe_clickhouse_query_duration
from app.config import settings


class TraceFetcher(ABC):
    @abstractmethod
    async def fetch_spans(self, trace_id: str) -> List[Span]:
        """从 ClickHouse 获取 trace 所有 span"""
        pass


class TraceFetcherImpl(TraceFetcher):
    async def fetch_spans(self, trace_id: str) -> List[Span]:
        """从 ClickHouse 获取 trace 所有 span"""
        from app.domain.entities.system import SystemClickhouseConfig
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy import select

        # TODO: 从数据库读取 ClickHouse 配置，这里简化为使用环境配置
        client = ClickHouseClient(
            endpoint=settings.clickhouse_endpoint,
            database=settings.clickhouse_database,
            username=settings.clickhouse_username,
            password=settings.clickhouse_password if settings.clickhouse_password else None
        )

        start_time = time.time()
        spans = []

        try:
            if settings.clickhouse_source_type == "opik":
                spans = await self._fetch_opik(client, trace_id)
            elif settings.clickhouse_source_type == "langfuse":
                spans = await self._fetch_langfuse(client, trace_id)

            duration = time.time() - start_time
            observe_clickhouse_query_duration(duration)
            logger.info(f"Fetched {len(spans)} spans for trace {trace_id} in {duration:.2f}s")

            return spans
        finally:
            client.close()

    async def _fetch_opik(self, client: ClickHouseClient, trace_id: str) -> List[Span]:
        """拉取 Opik 格式的 Trace"""
        query = """
        SELECT
            id as span_id,
            trace_id,
            name,
            type as span_type,
            start_time,
            end_time,
            duration_ms,
            input,
            output,
            ttft_ms,
            tpot_ms,
            input_tokens,
            output_tokens,
            cpu_usage,
            memory_usage
        FROM opik.spans
        WHERE trace_id = %s
        ORDER BY start_time ASC
        """
        rows = await client.query(query, (trace_id,))
        spans = []
        for row in rows:
            metrics = SpanMetrics(
                ttft_ms=row.ttft_ms,
                tpot_ms=row.tpot_ms,
                input_tokens=row.input_tokens or 0,
                output_tokens=row.output_tokens or 0,
                cpu_usage=row.cpu_usage,
                memory_usage=row.memory_usage
            )
            span = Span(
                span_id=str(row.span_id),
                trace_id=row.trace_id,
                span_type=row.span_type or "unknown",
                name=row.name,
                input=row.input,
                output=row.output,
                start_time_ms=int(row.start_time * 1000),
                end_time_ms=int(row.end_time * 1000),
                duration_ms=int(row.duration_ms),
                metrics=metrics
            )
            spans.append(span)
        return spans

    async def _fetch_langfuse(self, client: ClickHouseClient, trace_id: str) -> List[Span]:
        """拉取 Langfuse 格式的 Trace"""
        query = """
        SELECT
            id as span_id,
            traceId as trace_id,
            name,
            type as span_type,
            startTime,
            endTime,
            latency_ms as duration_ms,
            input,
            output
        FROM langfuse.observations
        WHERE traceId = %s
        ORDER BY startTime ASC
        """
        rows = await client.query(query, (trace_id,))
        spans = []
        for row in rows:
            metrics = SpanMetrics()
            # TODO: 提取 Langfuse 特定格式的指标
            span = Span(
                span_id=str(row.span_id),
                trace_id=row.trace_id,
                span_type=row.span_type or "unknown",
                name=row.name,
                input=row.input,
                output=row.output,
                start_time_ms=int(row.startTime * 1000),
                end_time_ms=int(row.endTime * 1000),
                duration_ms=int(row.duration_ms),
                metrics=metrics
            )
            spans.append(span)
        return spans
