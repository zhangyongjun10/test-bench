"""配置文件"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""

    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/testbench"

    # ClickHouse 连接配置
    clickhouse_endpoint: Optional[str] = None
    clickhouse_database: str = "opik"
    clickhouse_username: str = "default"
    clickhouse_password: Optional[str] = None
    clickhouse_source_type: str = "opik"  # opik or langfuse

    # 加密密钥 (32 bytes base64 encoded)
    encryption_key: str = "your-encryption-key-change-in-production"

    # 服务
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # 数据保留天数
    data_retention_days: int = 30

    # Agent 调用超时
    agent_timeout_seconds: int = 1200

    model_config = {
        "env_file": ".env",
        "case_sensitive": False
    }


settings = Settings()
