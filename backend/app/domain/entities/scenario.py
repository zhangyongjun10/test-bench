"""测试场景实体"""

import uuid
from datetime import UTC, datetime
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Double, Integer
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class Scenario(Base):
    """测试场景"""

    __tablename__ = "scenarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    prompt = Column(Text, nullable=False)
    # 旧版比对字段（保留向后兼容）
    baseline_result = Column(Text)
    llm_count_min = Column(Integer, nullable=False, default=0)
    llm_count_max = Column(Integer, nullable=False, default=999)
    compare_result = Column(Boolean, nullable=False, default=True)
    compare_process = Column(Boolean, nullable=False, default=False)
    # 新版基线相关字段
    baseline_tool_calls = Column(Text)  # JSON 格式存储工具调用基线
    process_threshold = Column(Double, nullable=False, default=60.0)  # 过程通过阈值
    result_threshold = Column(Double, nullable=False, default=60.0)  # 结果通过阈值
    tool_count_tolerance = Column(Integer, nullable=False, default=0)  # 工具次数容忍度
    compare_enabled = Column(Boolean, nullable=False, default=True)  # 是否启用自动比对
    enable_llm_verification = Column(Boolean, nullable=False, default=True)  # 是否启用 LLM 验证
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    deleted_at = Column(DateTime(timezone=True))
