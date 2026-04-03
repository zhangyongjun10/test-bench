"""执行模型"""

from uuid import UUID
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.domain.entities.execution import ExecutionStatus


class CreateExecutionRequest(BaseModel):
    """创建执行请求"""

    agent_id: UUID
    scenario_id: UUID
    llm_model_id: Optional[UUID] = None


class ExecutionResponse(BaseModel):
    """执行响应"""

    id: UUID
    agent_id: Optional[UUID]
    scenario_id: Optional[UUID]
    llm_model_id: Optional[UUID]
    trace_id: Optional[str]
    status: str
    comparison_score: Optional[float]
    comparison_passed: Optional[bool]
    error_message: Optional[str]
    original_request: Optional[str]
    original_response: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SpanResponse(BaseModel):
    """Span 响应（用于回放）"""

    span_id: str
    span_type: str
    name: str
    input: Optional[str]
    output: Optional[str]
    duration_ms: Optional[int]
    ttft_ms: Optional[float]
    tpot_ms: Optional[float]


class ExecutionTraceResponse(BaseModel):
    """执行 Trace 响应"""

    trace_id: str
    spans: list[SpanResponse]


class ComparisonResult(BaseModel):
    """比对结果"""

    score: float
    passed: bool
    reason: str
