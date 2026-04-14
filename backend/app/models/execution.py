"""鎵ц妯″瀷"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateExecutionRequest(BaseModel):
    """鍒涘缓鎵ц璇锋眰"""

    agent_id: UUID
    scenario_id: UUID
    llm_model_id: UUID | None = None


class ExecutionResponse(BaseModel):
    """鎵ц鍝嶅簲"""

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
    """Span 鍝嶅簲锛堢敤浜庡洖鏀撅級"""

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
    """鎵ц Trace 鍝嶅簲"""

    trace_id: str
    spans: list[SpanResponse]


class ComparisonResult(BaseModel):
    """姣斿缁撴灉"""

    score: float
    passed: bool
    reason: str


class ConcurrentExecutionRequest(BaseModel):
    input: str = Field(..., min_length=1)
    concurrency: int = Field(..., ge=1)
    model: str = Field(..., min_length=1)
    scenario_id: UUID | None = None
    concurrent_mode: str | None = "single_instance"
    llm_model_id: UUID | None = None
    agent_id: UUID | None = None


class ConcurrentExecutionResponse(BaseModel):
    batch_id: str
    message: str
