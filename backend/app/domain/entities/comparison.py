"""比对结果实体"""

import uuid
from datetime import datetime
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
    trace_id = Column(String(255))
    process_score = Column(Double)
    result_score = Column(Double)
    overall_passed = Column(Boolean)
    details_json = Column(Text)
    status = Column(String(50), nullable=False, default=ComparisonStatus.PENDING)
    error_message = Column(Text)
    retry_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True))
