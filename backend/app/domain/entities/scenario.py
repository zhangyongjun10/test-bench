"""测试 Case 相关实体定义。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Double, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class Scenario(Base):
    """定义单条 Case 主记录，只保存可复用的测试内容与比对规则。"""

    __tablename__ = "scenarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    prompt = Column(Text, nullable=False)
    baseline_result = Column(Text)
    llm_count_min = Column(Integer, nullable=False, default=0)
    llm_count_max = Column(Integer, nullable=False, default=999)
    compare_result = Column(Boolean, nullable=False, default=True)
    compare_process = Column(Boolean, nullable=False, default=False)
    baseline_tool_calls = Column(Text)
    process_threshold = Column(Double, nullable=False, default=60.0)
    result_threshold = Column(Double, nullable=False, default=60.0)
    tool_count_tolerance = Column(Integer, nullable=False, default=0)
    compare_enabled = Column(Boolean, nullable=False, default=True)
    enable_llm_verification = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    deleted_at = Column(DateTime(timezone=True))


class ScenarioAgent(Base):
    """定义 Case 与 Agent 的多对多关联，避免同一 Agent 在同一 Case 上重复绑定。"""

    __tablename__ = "scenario_agents"
    __table_args__ = (
        UniqueConstraint("scenario_id", "agent_id", name="uq_scenario_agents_scenario_id_agent_id"),
    )

    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), primary_key=True, nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), primary_key=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
