"""LiteLLM Trace TTFT/TPOT 补值测试。"""

import pytest

from app.domain.entities.trace import Span, SpanMetrics
from app.services.litellm_trace_timing_service import LiteLLMTraceTimingService


# 构造 OpenAI LLM span；默认带有 ClickHouse 原始 TTFT，便于验证 PG 覆盖与兜底逻辑。
def build_llm_span(call_id: str | None, ttft_ms: float | None, provider: str = "openai") -> Span:
    return Span(
        span_id=f"span-{call_id or 'none'}",
        trace_id="trace-1",
        span_type="llm",
        name="llm-call",
        provider=provider,
        input="input",
        output="output",
        start_time_ms=0,
        end_time_ms=1000,
        duration_ms=1000,
        metrics=SpanMetrics(ttft_ms=ttft_ms, input_tokens=10, output_tokens=20),
        openclaw_llm_call_id=call_id,
    )


@pytest.mark.asyncio
async def test_enrich_spans_ttft_prefers_pg_value_and_pg_based_tpot(monkeypatch):
    service = LiteLLMTraceTimingService()
    span = build_llm_span("call-1", 120.0)

    async def fake_fetch(trace_id: str) -> dict[str, dict[str, float]]:
        assert trace_id == "trace-1"
        return {"call-1": {"ttft_ms": 345.0, "post_first_token_duration_ms": 456.0}}

    monkeypatch.setattr(service, "_fetch_timings_by_call_id", fake_fetch)

    await service.enrich_spans_ttft("trace-1", [span])

    assert span.metrics.ttft_ms == 345.0
    assert span.metrics.tpot_ms == pytest.approx(456.0 / 19)


@pytest.mark.asyncio
async def test_enrich_spans_ttft_keeps_clickhouse_ttft_when_pg_missing(monkeypatch):
    service = LiteLLMTraceTimingService()
    span = build_llm_span("call-1", 120.0)

    async def fake_fetch(trace_id: str) -> dict[str, dict[str, float]]:
        assert trace_id == "trace-1"
        return {}

    monkeypatch.setattr(service, "_fetch_timings_by_call_id", fake_fetch)

    await service.enrich_spans_ttft("trace-1", [span])

    assert span.metrics.ttft_ms == 120.0


@pytest.mark.asyncio
async def test_enrich_spans_ttft_ignores_non_openai_and_missing_call_id(monkeypatch):
    service = LiteLLMTraceTimingService()
    openai_without_call_id = build_llm_span(None, None)
    litellm_span = build_llm_span("call-2", 55.0, provider="litellm")

    async def fake_fetch(trace_id: str) -> dict[str, dict[str, float]]:
        raise AssertionError(f"should not query pg for trace {trace_id}")

    monkeypatch.setattr(service, "_fetch_timings_by_call_id", fake_fetch)

    await service.enrich_spans_ttft("trace-1", [openai_without_call_id, litellm_span])

    assert openai_without_call_id.metrics.ttft_ms is None
    assert litellm_span.metrics.ttft_ms == 55.0


def test_normalize_asyncpg_dsn_accepts_sqlalchemy_scheme():
    normalized = LiteLLMTraceTimingService._normalize_asyncpg_dsn(
        "postgresql+asyncpg://user:pass@127.0.0.1:5432/litellm"
    )

    assert normalized == "postgresql://user:pass@127.0.0.1:5432/litellm"


def test_calculate_tpot_ms_prefers_post_first_token_duration():
    tpot_ms = LiteLLMTraceTimingService._calculate_tpot_ms(
        duration_ms=1000,
        ttft_ms=400.0,
        output_tokens=4,
        post_first_token_duration_ms=450.0,
    )

    assert tpot_ms == pytest.approx(150.0)


def test_calculate_tpot_ms_falls_back_to_duration_minus_ttft():
    tpot_ms = LiteLLMTraceTimingService._calculate_tpot_ms(
        duration_ms=1000,
        ttft_ms=400.0,
        output_tokens=4,
    )

    assert tpot_ms == pytest.approx(200.0)
