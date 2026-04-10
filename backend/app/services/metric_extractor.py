"""Metric extraction service."""

from typing import List

import numpy as np

from app.domain.entities.trace import (
    ExecutionMetrics,
    LLMMetrics,
    RuntimeMetrics,
    Span,
    ToolMetrics,
)


class MetricExtractor:
    """Aggregate execution metrics from trace spans."""

    def extract(self, spans: List[Span]) -> ExecutionMetrics:
        llm_spans = [span for span in spans if span.span_type == "llm"]
        tool_spans = [span for span in spans if span.span_type == "tool"]
        runtime_spans = [span for span in spans if span.span_type == "runtime"]

        llm_metrics = self._extract_llm_metrics(llm_spans)
        runtime_metrics = self._extract_runtime_metrics(runtime_spans) if runtime_spans else None
        tool_metrics = self._extract_tool_metrics(tool_spans) if tool_spans else None

        return ExecutionMetrics(
            llm=llm_metrics,
            runtime=runtime_metrics,
            tool=tool_metrics,
        )

    def _extract_llm_metrics(self, spans: List[Span]) -> LLMMetrics:
        ttft_list = [span.metrics.ttft_ms for span in spans if span.metrics.ttft_ms is not None]
        tpot_list = [span.metrics.tpot_ms for span in spans if span.metrics.tpot_ms is not None]
        input_tokens = sum(span.metrics.input_tokens for span in spans)
        output_tokens = sum(span.metrics.output_tokens for span in spans)

        percentiles = [50, 75, 90, 99]
        ttft_result = self._build_percentile_map(ttft_list, percentiles)
        tpot_result = self._build_percentile_map(tpot_list, percentiles)

        return LLMMetrics(
            ttft_ms=ttft_result,
            tpot_ms=tpot_result,
            total_tokens=input_tokens + output_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _extract_runtime_metrics(self, spans: List[Span]) -> RuntimeMetrics:
        cpu_values = [span.metrics.cpu_usage for span in spans if span.metrics.cpu_usage is not None]
        memory_values = [span.metrics.memory_usage for span in spans if span.metrics.memory_usage is not None]
        gc_count = sum(span.metrics.gc_count for span in spans)
        gc_duration = sum(span.metrics.gc_duration_ms for span in spans)

        avg_cpu = float(np.mean(cpu_values)) if cpu_values else None
        avg_memory = float(np.mean(memory_values)) if memory_values else None

        return RuntimeMetrics(
            avg_cpu_usage=avg_cpu,
            avg_memory_usage=avg_memory,
            total_gc_count=gc_count,
            total_gc_duration_ms=gc_duration,
        )

    def _extract_tool_metrics(self, spans: List[Span]) -> ToolMetrics:
        durations = [span.duration_ms for span in spans if span.duration_ms is not None]
        total_calls = len(spans)
        error_count = 0
        error_rate = 0.0

        if not durations:
            return ToolMetrics(
                total_calls=total_calls,
                error_count=error_count,
                error_rate=error_rate,
                avg_duration_ms=0,
                p50_duration_ms=0,
                p99_duration_ms=0,
            )

        avg_duration = float(np.mean(durations))
        p50 = float(np.percentile(durations, 50))
        p99 = float(np.percentile(durations, 99))

        return ToolMetrics(
            total_calls=total_calls,
            error_count=error_count,
            error_rate=error_rate,
            avg_duration_ms=avg_duration,
            p50_duration_ms=p50,
            p99_duration_ms=p99,
        )

    @staticmethod
    def _build_percentile_map(values: list[float], percentiles: list[int]) -> dict[float, float]:
        if not values:
            return {percentile: 0.0 for percentile in percentiles}

        result = np.percentile(values, percentiles)
        return {percentile: float(value) for percentile, value in zip(percentiles, result)}
