"""Replay task entity."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class ReplayTaskStatus:
    QUEUED = "queued"
    RUNNING = "running"
    PULLING_TRACE = "pulling_trace"
    COMPARING = "comparing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReplayBaselineSource:
    SCENARIO_BASELINE = "scenario_baseline"
    REFERENCE_EXECUTION = "reference_execution"


class ReplayTask(Base):
    """A user-triggered end-to-end replay task."""

    __tablename__ = "replay_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_execution_id = Column(UUID(as_uuid=True), ForeignKey("execution_jobs.id"), nullable=False, index=True)
    replay_execution_id = Column(UUID(as_uuid=True), ForeignKey("execution_jobs.id"), nullable=False, index=True)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False, index=True)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True)
    baseline_source = Column(String(50), nullable=False)
    baseline_snapshot_json = Column(Text, nullable=False)
    idempotency_key = Column(String(255), nullable=False, unique=True, index=True)
    llm_model_id = Column(UUID(as_uuid=True), ForeignKey("llm_models.id"), nullable=False, index=True)
    status = Column(String(50), nullable=False, default=ReplayTaskStatus.QUEUED, index=True)
    comparison_id = Column(UUID(as_uuid=True), ForeignKey("comparison_results.id"), nullable=True)
    overall_passed = Column(Boolean, nullable=True)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
