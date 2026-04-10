"""系统配置实体"""

from datetime import UTC, datetime
from sqlalchemy import Column, String, Text, Integer, DateTime
from app.core.db import Base


class SystemClickhouseConfig(Base):
    """ClickHouse 系统配置"""

    __tablename__ = "system_clickhouse_config"

    id = Column(Integer, primary_key=True, default=1)
    endpoint = Column(String(2048), nullable=False)
    database = Column(String(255), nullable=False)
    username = Column(String(255))
    password_encrypted = Column(Text)
    source_type = Column(String(50), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
