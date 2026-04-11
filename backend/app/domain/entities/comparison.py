"""比对结果实体"""

import uuid
from datetime import UTC, datetime
from sqlalchemy import Column, String, Text, ForeignKey, Double, Boolean, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class ComparisonStatus:
    """比对状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ComparisonResult(Base):
    """比对结果"""

    __tablename__ = "comparison_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("execution_jobs.id"), nullable=False, index=True)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False, index=True)
    llm_model_id = Column(UUID(as_uuid=True), ForeignKey("llm_models.id"), nullable=True, index=True)
    replay_task_id = Column(UUID(as_uuid=True), ForeignKey("replay_tasks.id"), nullable=True, index=True)
    source_type = Column(String(50), nullable=False, default="execution_auto", index=True)
    baseline_source = Column(String(50), nullable=True)
    trace_id = Column(String(255))
    process_score = Column(Double)
    result_score = Column(Double)
    overall_passed = Column(Boolean)
    details_json = Column(Text)
    status = Column(String(50), nullable=False, default=ComparisonStatus.PENDING)
    error_message = Column(Text)
    retry_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    completed_at = Column(DateTime(timezone=True))


class ComparisonSourceType:
    EXECUTION_AUTO = "execution_auto"
    RECOMPARE = "recompare"
    REPLAY = "replay"
