"""执行模型"""

from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CreateExecutionRequest(BaseModel):
    """创建执行请求"""

    agent_id: UUID
    scenario_id: UUID
    llm_model_id: UUID


class ExecutionResponse(BaseModel):
    """执行响应"""

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
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpanResponse(BaseModel):
    """Span 响应（用于回放）"""

    span_id: str
    span_type: str
    name: str
    provider: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    input: str | None
    output: str | None
    duration_ms: int | None
    ttft_ms: float | None
    tpot_ms: float | None


class ExecutionTraceResponse(BaseModel):
    """执行 Trace 响应"""

    trace_id: str
    spans: list[SpanResponse]


class ComparisonResult(BaseModel):
    """比对结果"""

    score: float
    passed: bool
    reason: str
