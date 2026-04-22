"""执行任务实体"""

import uuid
from datetime import UTC, datetime
from sqlalchemy import Column, String, Text, ForeignKey, Double, Boolean, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class ExecutionJob(Base):
    """执行任务"""

    __tablename__ = "execution_jobs"
    __table_args__ = (
        # Trace 列表与回放排查都会按 trace_id 精确定位执行记录，索引需要覆盖 execution_jobs 上的 trace_id 查询路径。
        Index("ix_execution_jobs_trace_id", "trace_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False)
    llm_model_id = Column(UUID(as_uuid=True), ForeignKey("llm_models.id"))
    user_session = Column(String(255), nullable=False)
    run_source = Column(String(50), nullable=False, default="normal")
    parent_execution_id = Column(UUID(as_uuid=True), ForeignKey("execution_jobs.id"), nullable=True)
    request_snapshot_json = Column(Text)
    trace_id = Column(String(255))
    batch_id = Column(String(255))
    status = Column(String(50), nullable=False)
    original_request = Column(Text)
    original_response = Column(Text)
    error_message = Column(Text)
    comparison_score = Column(Double)
    comparison_passed = Column(Boolean)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


# 状态枚举
class ExecutionStatus:
    QUEUED = "queued"
    RUNNING = "running"
    PULLING_TRACE = "pulling_trace"
    COMPARING = "comparing"
    COMPLETED = "completed"
    COMPLETED_WITH_MISMATCH = "completed_with_mismatch"
    FAILED = "failed"


class ExecutionRunSource:
    NORMAL = "normal"
    REPLAY = "replay"
