"""Replay API models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.comparison import DetailedComparisonResponse
from app.models.execution import ExecutionResponse


class CreateReplayRequest(BaseModel):
    original_execution_id: UUID
    baseline_source: str
    llm_model_id: UUID
    idempotency_key: str


class ReplayTaskResponse(BaseModel):
    id: UUID
    original_execution_id: UUID
    replay_execution_id: UUID
    scenario_id: UUID
    agent_id: UUID
    baseline_source: str
    baseline_snapshot_json: str
    idempotency_key: str
    llm_model_id: UUID
    status: str
    comparison_id: UUID | None
    overall_passed: bool | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ReplayDetailResponse(BaseModel):
    replay_task: ReplayTaskResponse
    original_execution: ExecutionResponse
    replay_execution: ExecutionResponse
    comparison: DetailedComparisonResponse | None = None


class ReplayHistoryResponse(BaseModel):
    total: int
    items: list[ReplayTaskResponse]


class ReplayRecompareResponse(BaseModel):
    success: bool
    message: str
