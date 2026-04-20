"""并发执行批次实体。"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.db import Base


# 并发执行批次状态枚举；用于描述批次整体是否仍在运行、已完成或存在失败。
class ExecutionBatchStatus:
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    FAILED = "failed"


# 并发执行批次实体；保存批次级请求数量和准备/启动失败计数，避免只看 execution 明细时丢失准备阶段异常。
class ExecutionBatch(Base):
    """并发执行批次表。"""

    __tablename__ = "execution_batches"

    id = Column(String(255), primary_key=True)
    requested_concurrency = Column(Integer, nullable=False)
    prepared_count = Column(Integer, nullable=False, default=0)
    started_count = Column(Integer, nullable=False, default=0)
    prepare_failed_count = Column(Integer, nullable=False, default=0)
    start_mark_failed_count = Column(Integer, nullable=False, default=0)
    status = Column(String(50), nullable=False, default=ExecutionBatchStatus.QUEUED)
    error_message = Column(Text)
    agent_started_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
