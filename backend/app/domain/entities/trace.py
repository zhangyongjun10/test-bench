"""Trace 数据实体"""

from typing import List, Optional
from dataclasses import dataclass


@dataclass
class SpanMetrics:
    """Span 指标"""

    ttft_ms: Optional[float] = None
    tpot_ms: Optional[float] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    gc_count: int = 0
    gc_duration_ms: float = 0.0


@dataclass
class Span:
    """Trace Span"""

    span_id: str
    trace_id: str
    span_type: str  # llm | tool | runtime | http
    name: str
    input: Optional[str]
    output: Optional[str]
    start_time_ms: Optional[int]
    end_time_ms: Optional[int]
    duration_ms: Optional[int]
    metrics: SpanMetrics


@dataclass
class LLMMetrics:
    """LLM 聚合指标"""

    ttft_ms: dict[float, float]  # percentile -> value
    tpot_ms: dict[float, float]
    total_tokens: int
    input_tokens: int
    output_tokens: int


@dataclass
class RuntimeMetrics:
    """Runtime 聚合指标"""

    avg_cpu_usage: Optional[float]
    avg_memory_usage: Optional[float]
    total_gc_count: int
    total_gc_duration_ms: float


@dataclass
class ToolMetrics:
    """工具调用指标"""

    total_calls: int
    error_count: int
    error_rate: float
    avg_duration_ms: float
    p50_duration_ms: float
    p99_duration_ms: float


@dataclass
class ExecutionMetrics:
    """执行聚合指标"""

    llm: LLMMetrics
    runtime: Optional[RuntimeMetrics]
    tool: Optional[ToolMetrics]
