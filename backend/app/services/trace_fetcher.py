"""Trace 拉取服务"""

from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
import json
import time
from app.domain.entities.trace import Span, SpanMetrics
from app.clients.clickhouse_client import ClickHouseClient
from app.core.logger import logger
from app.core.metrics import observe_clickhouse_query_duration
from app.core.encryption import encryption_service
from app.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.domain.entities.system import SystemClickhouseConfig


class TraceFetcher(ABC):
    @abstractmethod
    async def fetch_spans(self, trace_id: str) -> List[Span]:
        """从 ClickHouse 获取 trace 所有 span"""
        pass

    @abstractmethod
    async def get_trace_id_by_run_id(self, run_id: str) -> Optional[str]:
        """根据 runId 从 opik.traces.metadata.runId 查询真实的 trace_id"""
        pass


class TraceFetcherImpl(TraceFetcher):
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _get_span_sort_key(span: Span, original_index: int) -> tuple[int, int, int]:
        """Trace 展示顺序按开始时间到秒分组；同秒时再按结束时间和原始顺序稳定排序。"""

        start_time_ms = span.start_time_ms if span.start_time_ms is not None else 0
        end_time_ms = span.end_time_ms if span.end_time_ms is not None else start_time_ms
        return (start_time_ms // 1000, end_time_ms, original_index)

    def _sort_spans_for_display(self, spans: List[Span]) -> List[Span]:
        """统一整理 Trace 展示顺序，避免毫秒抖动把同秒 tool 排到下一轮 LLM 后面。"""

        indexed_spans = list(enumerate(spans))
        indexed_spans.sort(key=lambda item: self._get_span_sort_key(item[1], item[0]))
        return [span for _, span in indexed_spans]

    async def fetch_spans(self, trace_id: str) -> List[Span]:
        """从 ClickHouse 获取 trace 所有 span"""
        client = await self._create_client()
        if not client:
            logger.warning("ClickHouse not configured, returning empty spans")
            return []

        start_time = time.time()
        spans = []

        try:
            config = await self._get_config()
            if config and config.source_type:
                if config.source_type == "opik":
                    spans = await self._fetch_opik(client, trace_id)
                elif config.source_type == "langfuse":
                    spans = await self._fetch_langfuse(client, trace_id)
            elif settings.clickhouse_source_type:
                # fallback to environment config if no db config
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

    async def get_trace_id_by_run_id(self, run_id: str) -> Optional[str]:
        """根据 runId 从 opik.traces.metadata.runId 查询真实的 trace_id"""
        client = await self._create_client()
        if not client:
            return None
        try:
            return await self._get_trace_id_by_run_id(client, run_id)
        finally:
            client.close()

    async def _get_config(self) -> Optional[SystemClickhouseConfig]:
        """从数据库获取 ClickHouse 配置"""
        result = await self.session.execute(select(SystemClickhouseConfig).where(SystemClickhouseConfig.id == 1))
        return result.scalar_one_or_none()

    async def _create_client(self) -> Optional[ClickHouseClient]:
        """创建 ClickHouse 客户端，优先使用数据库配置，回退到环境变量"""
        config = await self._get_config()

        endpoint: Optional[str] = None
        database: Optional[str] = None
        username: Optional[str] = None
        password: Optional[str] = None
        source_type: Optional[str] = None

        if config:
            # 从数据库读取配置
            endpoint = config.endpoint
            database = config.database
            username = config.username
            if config.password_encrypted:
                password = encryption_service.decrypt(config.password_encrypted)
            source_type = config.source_type
            logger.debug(f"Using ClickHouse configuration from database: {endpoint}")
        else:
            # 回退到环境变量配置
            endpoint = settings.clickhouse_endpoint
            database = settings.clickhouse_database
            username = settings.clickhouse_username
            password = settings.clickhouse_password
            source_type = settings.clickhouse_source_type
            logger.debug("Using ClickHouse configuration from environment variables")

        if not endpoint:
            return None

        return ClickHouseClient(
            endpoint=endpoint,
            database=database or "default",
            username=username,
            password=password
        )

    async def _get_trace_id_by_run_id(self, client: ClickHouseClient, run_id: str) -> Optional[str]:
        """根据 runId (agent 返回的 id) 从 opik.traces 查询真实的 trace_id"""
        # 先试 opik.traces，如果 database 已经是 opik 试 traces
        # clickhouse-driver 参数占位问题，直接字符串转义
        logger.info(f"[DEBUG] Looking for run_id={run_id} in ClickHouse")
        run_id_escaped = run_id.replace("'", "\\'")
        query_variants = [
            ("opik.traces", f"""
            SELECT id
            FROM opik.traces
            WHERE JSONExtractString(metadata, 'runId') = '{run_id_escaped}'
            LIMIT 1
            """),
            ("traces", f"""
            SELECT id
            FROM traces
            WHERE JSONExtractString(metadata, 'runId') = '{run_id_escaped}'
            LIMIT 1
            """)
        ]
        for table_name, query in query_variants:
            logger.info(f"[DEBUG] Trying table {table_name}...")
            rows = await client.query(query)
            logger.info(f"[DEBUG] {table_name} returned {len(rows)} rows")
            if rows and len(rows) > 0:
                result = str(rows[0]['id'])
                logger.info(f"[DEBUG] Found id={result} in {table_name}")
                return result
        logger.warning(f"[DEBUG] No trace found for run_id={run_id} in any table")
        return None

    async def _fetch_opik(self, client: ClickHouseClient, trace_id: str) -> List[Span]:
        """拉取 Opik 格式的 Trace
        如果传入的是 runId 会自动查询得到真实 trace_id
        """
        # clickhouse-driver 参数占位问题，直接字符串转义
        trace_id_escaped = trace_id.replace("'", "\\'")
        # 尝试两种表名格式（opik.spans 或 spans，取决于 database 是否已经是 opik）
        query_variants = [
            ("opik.spans", f"""
            SELECT
                id as span_id,
                trace_id,
                name,
                provider,
                type as span_type,
                JSONExtractString(metadata, 'requester_metadata', 'openclaw_llm_call_id') as openclaw_llm_call_id,
                start_time,
                end_time,
                duration,
                ttft,
                input,
                output,
                usage
            FROM opik.spans
            WHERE trace_id = '{trace_id_escaped}'
            ORDER BY start_time ASC
            """),
            ("spans", f"""
            SELECT
                id as span_id,
                trace_id,
                name,
                provider,
                type as span_type,
                JSONExtractString(metadata, 'requester_metadata', 'openclaw_llm_call_id') as openclaw_llm_call_id,
                start_time,
                end_time,
                duration,
                ttft,
                input,
                output,
                usage
            FROM spans
            WHERE trace_id = '{trace_id_escaped}'
            ORDER BY start_time ASC
            """)
        ]
        rows = []
        for table_name, query in query_variants:
            rows = await client.query(query)
            if len(rows) > 0:
                break

        # 如果直接查不到，尝试当成 runId 去 traces 表查询真实 trace_id
        if len(rows) == 0:
            real_trace_id = await self._get_trace_id_by_run_id(client, trace_id)
            if real_trace_id:
                logger.info(f"Resolved runId {trace_id} -> real trace_id {real_trace_id}")
                trace_id = real_trace_id
                # 重新查询，再次尝试两种表名
                trace_id_escaped = trace_id.replace("'", "\\'")
                query_variants = [
                    ("opik.spans", f"""
                    SELECT
                        id as span_id,
                        trace_id,
                        name,
                        provider,
                        type as span_type,
                        JSONExtractString(metadata, 'requester_metadata', 'openclaw_llm_call_id') as openclaw_llm_call_id,
                        start_time,
                        end_time,
                        duration,
                        ttft,
                        input,
                        output,
                        usage
                    FROM opik.spans
                    WHERE trace_id = '{trace_id_escaped}'
                    ORDER BY start_time ASC
                    """),
                    ("spans", f"""
                    SELECT
                        id as span_id,
                        trace_id,
                        name,
                        provider,
                        type as span_type,
                        JSONExtractString(metadata, 'requester_metadata', 'openclaw_llm_call_id') as openclaw_llm_call_id,
                        start_time,
                        end_time,
                        duration,
                        ttft,
                        input,
                        output,
                        usage
                    FROM spans
                    WHERE trace_id = '{trace_id_escaped}'
                    ORDER BY start_time ASC
                    """)
                ]
                for table_name, query in query_variants:
                    rows = await client.query(query)
                    if len(rows) > 0:
                        break

        # 去重：Opik 可能写入多条相同 span_id，只保留最后一条（完整数据）
        seen_span_ids = {}
        for row in rows:
            span_id = str(row['span_id'])
            seen_span_ids[span_id] = row  # 后出现的覆盖先出现的

        spans = []
        for row in seen_span_ids.values():
            ttft_ms = row['ttft'] * 1000 if row['ttft'] is not None else None
            duration_ms = int(row['duration']) if row['duration'] is not None else None

            # 从 usage 字段提取 token 统计
            input_tokens = 0
            output_tokens = 0
            usage_raw = row.get('usage')
            if usage_raw:
                try:
                    usage = json.loads(usage_raw) if isinstance(usage_raw, str) else usage_raw
                    input_tokens = int(usage.get('prompt_tokens', 0) or 0)
                    output_tokens = int(usage.get('completion_tokens', 0) or 0)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

            # 根据 duration 和 output_tokens 推算 TPOT
            tpot_ms = None
            if duration_ms is not None and ttft_ms is not None and output_tokens > 1:
                remaining_duration_ms = duration_ms - ttft_ms
                if remaining_duration_ms >= 0:
                    tpot_ms = remaining_duration_ms / (output_tokens - 1)

            metrics = SpanMetrics(
                ttft_ms=ttft_ms,
                tpot_ms=tpot_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cpu_usage=None,
                memory_usage=None
            )

            # start_time/end_time can be datetime objects from clickhouse_driver
            start_ms = None
            if row['start_time'] is not None:
                if hasattr(row['start_time'], 'timestamp'):
                    start_ms = int(row['start_time'].timestamp() * 1000)
                else:
                    start_ms = int(row['start_time'] * 1000)

            end_ms = None
            if row['end_time'] is not None:
                if hasattr(row['end_time'], 'timestamp'):
                    end_ms = int(row['end_time'].timestamp() * 1000)
                else:
                    end_ms = int(row['end_time'] * 1000)

            span = Span(
                span_id=str(row['span_id']),
                trace_id=row['trace_id'],
                span_type=row['span_type'] or "unknown",
                name=row['name'],
                provider=row.get('provider'),
                input=row['input'],
                output=row['output'],
                start_time_ms=start_ms,
                end_time_ms=end_ms,
                duration_ms=duration_ms,
                metrics=metrics,
                openclaw_llm_call_id=row.get('openclaw_llm_call_id') or None,
            )
            spans.append(span)

        return self._sort_spans_for_display(spans)

    async def _fetch_langfuse(self, client: ClickHouseClient, trace_id: str) -> List[Span]:
        """拉取 Langfuse 格式的 Trace"""
        # clickhouse-driver 参数占位问题，直接字符串转义
        trace_id_escaped = trace_id.replace("'", "\\'")
        # 尝试两种表名格式
        query_variants = [
            ("langfuse.observations", f"""
            SELECT
                id as span_id,
                traceId as trace_id,
                name,
                NULL as provider,
                type as span_type,
                startTime,
                endTime,
                latency_ms as duration_ms,
                input,
                output
            FROM langfuse.observations
            WHERE traceId = '{trace_id_escaped}'
            ORDER BY startTime ASC
            """),
            ("observations", f"""
            SELECT
                id as span_id,
                traceId as trace_id,
                name,
                NULL as provider,
                type as span_type,
                startTime,
                endTime,
                latency_ms as duration_ms,
                input,
                output
            FROM observations
            WHERE traceId = '{trace_id_escaped}'
            ORDER BY startTime ASC
            """)
        ]
        rows = []
        for table_name, query in query_variants:
            rows = await client.query(query)
            if len(rows) > 0:
                break
        # 去重：可能存在多条相同 span_id，只保留最后一条
        seen_span_ids = {}
        for row in rows:
            span_id = str(row['span_id'])
            seen_span_ids[span_id] = row  # 后出现的覆盖先出现的

        spans = []
        for row in seen_span_ids.values():
            metrics = SpanMetrics()
            # TODO: 提取 Langfuse 特定格式的指标

            # start_time can be None, handle same as opik
            start_ms = None
            if row['startTime'] is not None:
                if hasattr(row['startTime'], 'timestamp'):
                    start_ms = int(row['startTime'].timestamp() * 1000)
                else:
                    start_ms = int(row['startTime'] * 1000)

            end_ms = None
            if row['endTime'] is not None:
                if hasattr(row['endTime'], 'timestamp'):
                    end_ms = int(row['endTime'].timestamp() * 1000)
                else:
                    end_ms = int(row['endTime'] * 1000)

            duration_ms = int(row['duration_ms']) if row['duration_ms'] is not None else None

            span = Span(
                span_id=str(row['span_id']),
                trace_id=row['trace_id'],
                span_type=row['span_type'] or "unknown",
                name=row['name'],
                provider=row.get('provider'),
                input=row['input'],
                output=row['output'],
                start_time_ms=start_ms,
                end_time_ms=end_ms,
                duration_ms=duration_ms,
                metrics=metrics
            )
            spans.append(span)

        return self._sort_spans_for_display(spans)
