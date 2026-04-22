"""指标提取测试"""

import pytest
from app.services.metric_extractor import MetricExtractor
from app.domain.entities.trace import Span, SpanMetrics


def test_extract_llm_metrics():
    """测试提取 LLM 指标"""
    spans = [
        Span(
            span_id="1",
            trace_id="trace1",
            span_type="llm",
            name="llm-call",
            provider="openai",
            input="input",
            output="output",
            start_time_ms=0,
            end_time_ms=1000,
            duration_ms=1000,
            metrics=SpanMetrics(ttft_ms=100, tpot_ms=10, input_tokens=10, output_tokens=20)
        ),
        Span(
            span_id="2",
            trace_id="trace1",
            span_type="llm",
            name="llm-call",
            provider="openai",
            input="input",
            output="output",
            start_time_ms=0,
            end_time_ms=2000,
            duration_ms=2000,
            metrics=SpanMetrics(ttft_ms=200, tpot_ms=20, input_tokens=20, output_tokens=40)
        )
    ]

    extractor = MetricExtractor()
    metrics = extractor.extract(spans)

    assert metrics.llm is not None
    assert metrics.llm.total_tokens == 90  # (10+20) + (20+40)
    assert 100 <= metrics.llm.ttft_ms[50] <= 200


def test_extract_tool_metrics_ignores_none_duration():
    spans = [
        Span(
            span_id="tool-1",
            trace_id="trace1",
            span_type="tool",
            name="read",
            provider=None,
            input="input",
            output="output",
            start_time_ms=0,
            end_time_ms=15,
            duration_ms=15,
            metrics=SpanMetrics(),
        ),
        Span(
            span_id="tool-2",
            trace_id="trace1",
            span_type="tool",
            name="exec",
            provider=None,
            input="input",
            output="output",
            start_time_ms=20,
            end_time_ms=None,
            duration_ms=None,
            metrics=SpanMetrics(),
        ),
    ]

    extractor = MetricExtractor()
    metrics = extractor.extract(spans)

    assert metrics.tool is not None
    assert metrics.tool.total_calls == 2
    assert metrics.tool.avg_duration_ms == 15
    assert metrics.tool.p50_duration_ms == 15
    assert metrics.tool.p99_duration_ms == 15


def test_tpot_formula_excludes_ttft_and_first_token():
    # TPOT 定义为去掉首 token 等待时间后，剩余 token 的平均生成耗时。
    duration_ms = 1000
    ttft_ms = 400
    output_tokens = 4

    tpot_ms = (duration_ms - ttft_ms) / (output_tokens - 1)

    assert tpot_ms == pytest.approx(200.0)
