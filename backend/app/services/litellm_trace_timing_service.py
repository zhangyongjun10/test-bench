"""LiteLLM Trace timing service."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from app.config import settings
from app.core.logger import logger
from app.domain.entities.trace import Span


# LiteLLM timing 结果；同一条调用同时返回 TTFT 和首 token 后持续时长，便于页面使用统一口径展示 TTFT/TPOT。
LiteLLMTiming = dict[str, float]


class LiteLLMTraceTimingService:
    # LiteLLM PG 连接池按进程复用，避免每次打开 Trace 回放都重新建立数据库连接。
    _pool: Optional[asyncpg.Pool] = None
    _pool_lock = asyncio.Lock()

    # 按 trace_id 批量补齐 OpenAI LLM span 的 TTFT/TPOT；
    # TPOT 和输出吞吐量优先使用 LiteLLM PG 同源的 endTime - completionStartTime 口径。
    async def enrich_spans_ttft(self, trace_id: str, spans: list[Span]) -> None:
        target_spans = [
            span
            for span in spans
            if (span.span_type or "").lower() == "llm"
            and (span.provider or "").lower() == "openai"
            and getattr(span, "openclaw_llm_call_id", None)
        ]
        if not target_spans:
            return

        timing_by_call_id = await self._fetch_timings_by_call_id(trace_id)

        if timing_by_call_id:
            for span in target_spans:
                call_id = getattr(span, "openclaw_llm_call_id", None)
                if not call_id:
                    continue

                timing = timing_by_call_id.get(call_id)
                if timing is None:
                    continue

                span.metrics.ttft_ms = timing["ttft_ms"]
                span.metrics.tpot_ms = self._calculate_tpot_ms(
                    duration_ms=span.duration_ms,
                    ttft_ms=span.metrics.ttft_ms,
                    output_tokens=span.metrics.output_tokens,
                    post_first_token_duration_ms=timing.get("post_first_token_duration_ms"),
                )
                span.metrics.output_throughput_tps = self._calculate_output_throughput_tps(
                    output_tokens=span.metrics.output_tokens,
                    post_first_token_duration_ms=timing.get("post_first_token_duration_ms"),
                )

        for span in spans:
            if span.metrics.output_throughput_tps is None:
                span.metrics.output_throughput_tps = self._calculate_output_throughput_tps(
                    output_tokens=span.metrics.output_tokens,
                    post_first_token_duration_ms=None,
                )
            span.metrics.total_throughput_tps = self._calculate_total_throughput_tps(
                duration_ms=span.duration_ms,
                input_tokens=span.metrics.input_tokens,
                output_tokens=span.metrics.output_tokens,
            )

    # 从 LiteLLM SpendLogs 批量读取当前 trace 下的 timing，并按 openclaw_llm_call_id 构建唯一映射。
    async def _fetch_timings_by_call_id(self, trace_id: str) -> dict[str, LiteLLMTiming]:
        pool = await self._get_pool()
        if not pool:
            return {}

        query = """
            SELECT
                proxy_server_request->'metadata'->>'openclaw_llm_call_id' AS openclaw_llm_call_id,
                "startTime" AS start_time,
                "completionStartTime" AS completion_start_time,
                "endTime" AS end_time
            FROM "LiteLLM_SpendLogs"
            WHERE session_id = $1
        """

        async with pool.acquire() as connection:
            rows = await connection.fetch(query, trace_id)

        best_rows: dict[str, tuple[bool, datetime]] = {}
        timing_by_call_id: dict[str, LiteLLMTiming] = {}

        for row in rows:
            call_id = row["openclaw_llm_call_id"]
            start_time = row["start_time"]
            completion_start_time = row["completion_start_time"]
            end_time = row["end_time"]

            if not call_id or not start_time:
                continue

            # 多条记录命中同一个调用时，优先选择 completionStartTime 非空的记录；
            # 仍冲突时选择 startTime 最新的一条。
            candidate_rank = (completion_start_time is not None, start_time)
            previous_rank = best_rows.get(call_id)
            if previous_rank and previous_rank >= candidate_rank:
                continue
            best_rows[call_id] = candidate_rank

            if completion_start_time is None:
                timing_by_call_id.pop(call_id, None)
                continue

            ttft_ms = (completion_start_time - start_time).total_seconds() * 1000
            if ttft_ms < 0:
                logger.warning(
                    "Ignoring negative TTFT from LiteLLM SpendLogs trace_id=%s call_id=%s start_time=%s completion_start_time=%s",
                    trace_id,
                    call_id,
                    start_time,
                    completion_start_time,
                )
                timing_by_call_id.pop(call_id, None)
                continue

            timing: LiteLLMTiming = {"ttft_ms": ttft_ms}
            if end_time is not None:
                post_first_token_duration_ms = (end_time - completion_start_time).total_seconds() * 1000
                if post_first_token_duration_ms < 0:
                    logger.warning(
                        "Ignoring negative post-first-token duration from LiteLLM SpendLogs trace_id=%s call_id=%s completion_start_time=%s end_time=%s",
                        trace_id,
                        call_id,
                        completion_start_time,
                        end_time,
                    )
                else:
                    timing["post_first_token_duration_ms"] = post_first_token_duration_ms

            timing_by_call_id[call_id] = timing

        return timing_by_call_id

    # 仅在配置了 LiteLLM PG DSN 时创建连接池；未配置时安静降级为“不补值”模式。
    async def _get_pool(self) -> Optional[asyncpg.Pool]:
        if not settings.litellm_database_url:
            return None

        if self.__class__._pool is not None:
            return self.__class__._pool

        async with self.__class__._pool_lock:
            if self.__class__._pool is None:
                self.__class__._pool = await asyncpg.create_pool(
                    dsn=self._normalize_asyncpg_dsn(settings.litellm_database_url),
                    min_size=1,
                    max_size=5,
                    command_timeout=10,
                )
        return self.__class__._pool

    # 兼容 SQLAlchemy 风格的 postgresql+asyncpg DSN，转换后再交给 asyncpg 建连。
    @staticmethod
    def _normalize_asyncpg_dsn(dsn: str) -> str:
        parsed = urlsplit(dsn)
        if parsed.scheme == "postgresql+asyncpg":
            return urlunsplit(("postgresql", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
        if parsed.scheme == "postgres+asyncpg":
            return urlunsplit(("postgres", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
        return dsn

    # PG 补齐 TTFT 后需要同步重算 TPOT；
    # 优先使用 LiteLLM PG 同源的 endTime - completionStartTime，缺失时再回退到 duration_ms - ttft_ms。
    @staticmethod
    def _calculate_tpot_ms(
        duration_ms: Optional[int],
        ttft_ms: Optional[float],
        output_tokens: int,
        post_first_token_duration_ms: Optional[float] = None,
    ) -> Optional[float]:
        if output_tokens <= 1:
            return None

        if post_first_token_duration_ms is not None:
            if post_first_token_duration_ms < 0:
                return None
            return post_first_token_duration_ms / (output_tokens - 1)

        if duration_ms is None or ttft_ms is None:
            return None

        remaining_duration_ms = duration_ms - ttft_ms
        if remaining_duration_ms < 0:
            return None

        return remaining_duration_ms / (output_tokens - 1)

    # 总吞吐量包含输入与输出 token，分母为请求总耗时，用于反映端到端的 token 处理速率。
    @staticmethod
    def _calculate_total_throughput_tps(
        duration_ms: Optional[int],
        input_tokens: int,
        output_tokens: int,
    ) -> Optional[float]:
        if duration_ms is None or duration_ms <= 0:
            return None

        total_tokens = input_tokens + output_tokens
        if total_tokens <= 0:
            return None

        return total_tokens / (duration_ms / 1000)

    # 输出吞吐量只统计首 token 之后的输出速率，分母固定使用 PG 同源的 endTime - completionStartTime。
    @staticmethod
    def _calculate_output_throughput_tps(
        output_tokens: int,
        post_first_token_duration_ms: Optional[float],
    ) -> Optional[float]:
        if output_tokens <= 1:
            return None
        if post_first_token_duration_ms is None or post_first_token_duration_ms <= 0:
            return None

        return (output_tokens - 1) / (post_first_token_duration_ms / 1000)
