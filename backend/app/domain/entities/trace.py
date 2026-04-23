"""Trace 领域实体定义。"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SpanMetrics:
    """描述单个 Span 的性能指标，供 Trace 回放和聚合统计直接复用。"""

    ttft_ms: Optional[float] = None
    tpot_ms: Optional[float] = None
    output_throughput_tps: Optional[float] = None
    total_throughput_tps: Optional[float] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    gc_count: int = 0
    gc_duration_ms: float = 0.0


@dataclass
class Span:
    """表示一条 Trace 中的原始 Span 记录，并保留回放展示所需的上下文字段。"""

    span_id: str
    trace_id: str
    span_type: str  # llm | tool | runtime | http
    name: str
    provider: Optional[str]
    input: Optional[str]
    output: Optional[str]
    start_time_ms: Optional[int]
    end_time_ms: Optional[int]
    duration_ms: Optional[int]
    metrics: SpanMetrics
    openclaw_llm_call_id: Optional[str] = None


@dataclass
class LLMMetrics:
    """聚合整条执行链路中的 LLM 指标，主要用于统计视图而非单个 Span 展示。"""

    ttft_ms: dict[float, float]
    tpot_ms: dict[float, float]
    total_tokens: int
    input_tokens: int
    output_tokens: int


@dataclass
class RuntimeMetrics:
    """聚合运行时资源指标，帮助定位 CPU、内存和 GC 对链路的影响。"""

    avg_cpu_usage: Optional[float]
    avg_memory_usage: Optional[float]
    total_gc_count: int
    total_gc_duration_ms: float


@dataclass
class ToolMetrics:
    """聚合工具调用稳定性与耗时指标，便于分析链路中的工具瓶颈。"""

    total_calls: int
    error_count: int
    error_rate: float
    avg_duration_ms: float
    p50_duration_ms: float
    p99_duration_ms: float


@dataclass
class ExecutionMetrics:
    """汇总一次执行的 LLM、运行时和工具指标，供上层统一消费。"""

    llm: LLMMetrics
    runtime: Optional[RuntimeMetrics]
    tool: Optional[ToolMetrics]
