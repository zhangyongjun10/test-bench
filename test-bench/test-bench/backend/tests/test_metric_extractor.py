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
