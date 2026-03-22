"""指标提取服务"""

from typing import List
import numpy as np
from app.domain.entities.trace import Span, SpanMetrics, ExecutionMetrics, LLMMetrics, RuntimeMetrics, ToolMetrics


class MetricExtractor:
    """指标提取器"""

    def extract(self, spans: List[Span]) -> ExecutionMetrics:
        """从 spans 提取各类指标"""
        llm_spans = [s for s in spans if s.span_type == "llm"]
        tool_spans = [s for s in spans if s.span_type == "tool"]
        runtime_spans = [s for s in spans if s.span_type == "runtime"]

        llm_metrics = self._extract_llm_metrics(llm_spans)
        runtime_metrics = self._extract_runtime_metrics(runtime_spans) if runtime_spans else None
        tool_metrics = self._extract_tool_metrics(tool_spans) if tool_spans else None

        return ExecutionMetrics(
            llm=llm_metrics,
            runtime=runtime_metrics,
            tool=tool_metrics
        )

    def _extract_llm_metrics(self, spans: List[Span]) -> LLMMetrics:
        """提取 LLM 指标"""
        ttft_list = [s.metrics.ttft_ms for s in spans if s.metrics.ttft_ms is not None]
        tpot_list = [s.metrics.tpot_ms for s in spans if s.metrics.tpot_ms is not None]
        input_tokens = sum(s.metrics.input_tokens for s in spans)
        output_tokens = sum(s.metrics.output_tokens for s in spans)

        percentiles = [50, 75, 90, 99]
        ttft_result = {}
        tpot_result = {}

        if ttft_list:
            ttft_values = np.percentile(ttft_list, percentiles)
            for p, v in zip(percentiles, ttft_values):
                ttft_result[p] = float(v)
        else:
            for p in percentiles:
                ttft_result[p] = 0.0

        if tpot_list:
            tpot_values = np.percentile(tpot_list, percentiles)
            for p, v in zip(percentiles, tpot_values):
                tpot_result[p] = float(v)
        else:
            for p in percentiles:
                tpot_result[p] = 0.0

        return LLMMetrics(
            ttft_ms=ttft_result,
            tpot_ms=tpot_result,
            total_tokens=input_tokens + output_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )

    def _extract_runtime_metrics(self, spans: List[Span]) -> RuntimeMetrics:
        """提取 Runtime 指标"""
        cpu_values = [s.metrics.cpu_usage for s in spans if s.metrics.cpu_usage is not None]
        memory_values = [s.metrics.memory_usage for s in spans if s.metrics.memory_usage is not None]
        gc_count = sum(s.metrics.gc_count for s in spans)
        gc_duration = sum(s.metrics.gc_duration_ms for s in spans)

        avg_cpu = float(np.mean(cpu_values)) if cpu_values else None
        avg_memory = float(np.mean(memory_values)) if memory_values else None

        return RuntimeMetrics(
            avg_cpu_usage=avg_cpu,
            avg_memory_usage=avg_memory,
            total_gc_count=gc_count,
            total_gc_duration_ms=gc_duration
        )

    def _extract_tool_metrics(self, spans: List[Span]) -> ToolMetrics:
        """提取工具调用指标"""
        durations = [s.duration_ms for s in spans]
        total_calls = len(spans)
        # TODO: 错误计数需要错误标记
        error_count = 0
        error_rate = 0.0

        if not durations:
            return ToolMetrics(
                total_calls=0,
                error_count=0,
                error_rate=0,
                avg_duration_ms=0,
                p50_duration_ms=0,
                p99_duration_ms=0
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
            p99_duration_ms=p99
        )
