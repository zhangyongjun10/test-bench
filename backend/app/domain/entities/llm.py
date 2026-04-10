"""LLM 模型实体"""

import uuid
from datetime import UTC, datetime
from sqlalchemy import Column, String, Text, Integer, Double, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import Base


class LLMModel(Base):
    """LLM 比对模型配置"""

    __tablename__ = "llm_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    provider = Column(String(50), nullable=False)
    model_id = Column(String(255), nullable=False)
    base_url = Column(String(2048))
    api_key_encrypted = Column(Text, nullable=False)
    temperature = Column(Double, nullable=False, default=0.0)
    max_tokens = Column(Integer, nullable=False, default=1024)
    comparison_prompt = Column(Text)
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    deleted_at = Column(DateTime(timezone=True))
