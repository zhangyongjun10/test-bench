"""执行相关的 API 请求与响应模型。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateExecutionRequest(BaseModel):
    """创建单次测试执行时的请求体，要求显式指定比对模型以保证后续收口一致。"""

    agent_id: UUID
    scenario_id: UUID
    llm_model_id: UUID


class ExecutionResponse(BaseModel):
    """执行列表与详情共用的响应结构，完整暴露执行状态和回放关联信息。"""

    id: UUID
    agent_id: UUID | None
    scenario_id: UUID | None
    llm_model_id: UUID | None
    user_session: str | None
    run_source: str | None = None
    parent_execution_id: UUID | None = None
    request_snapshot_json: str | None = None
    trace_id: str | None
    status: str
    comparison_score: float | None
    comparison_passed: bool | None
    error_message: str | None
    original_request: str | None
    original_response: str | None
    replay_count: int = 0
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpanResponse(BaseModel):
    """Trace 回放中的单个 Span 响应，包含原始输入输出和派生性能指标。"""

    span_id: str
    span_type: str
    name: str
    provider: str | None = None
    start_time_ms: int | None = None
    end_time_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    input: str | None
    output: str | None
    duration_ms: int | None
    ttft_ms: float | None
    tpot_ms: float | None
    output_throughput_tps: float | None = None
    total_throughput_tps: float | None = None


class ExecutionTraceResponse(BaseModel):
    """执行 Trace 的聚合响应，顶部摘要和逐 Span 回放都依赖该结构。"""

    trace_id: str
    total_duration_ms: int = 0
    avg_ttft_ms: float | None = None
    avg_tpot_ms: float | None = None
    output_throughput_tps: float | None = None
    total_throughput_tps: float | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    spans: list[SpanResponse]


class ComparisonResult(BaseModel):
    """统一描述比对结论，供不同比对接口复用分数、结果和原因字段。"""

    score: float
    passed: bool
    reason: str


class ConcurrentExecutionRequest(BaseModel):
    """创建并发执行时的请求体，只暴露并发度、输入和比对模型等必要参数。"""

    input: str = Field(..., min_length=1)
    concurrency: int = Field(..., ge=1)
    scenario_id: UUID | None = None
    llm_model_id: UUID
    agent_id: UUID | None = None


class ConcurrentExecutionResponse(BaseModel):
    """并发执行创建成功后的响应，返回批次 ID 供前端轮询整体进度。"""

    batch_id: str
    message: str
