"""Agent 实体"""

import uuid
from datetime import UTC, datetime
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


# Agent 数据库实体，只保存连接配置和密钥信息；用户会话已迁移到 execution 级别隔离。
class Agent(Base):
    """Agent 注册表"""

    __tablename__ = "agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    base_url = Column(String(2048), nullable=False)
    api_key_encrypted = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    deleted_at = Column(DateTime(timezone=True))
