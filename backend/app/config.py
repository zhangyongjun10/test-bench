"""配置文件"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""

    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/testbench"
    # 数据库连接池常驻连接数；不要按 Agent 并发数放大，建议按数据库承载能力设置。
    db_pool_size: int = 20
    # 数据库连接池临时溢出连接数；用于吸收短时间突刺请求。
    db_max_overflow: int = 30
    # 获取数据库连接的等待秒数；超过后快速失败，避免请求无限挂起。
    db_pool_timeout: int = 30
    # 数据库空闲连接回收秒数；降低长时间运行后拿到失效连接的概率。
    db_pool_recycle_seconds: int = 1800
    # 并发执行链路同时进入数据库读写区的最大协程数；Agent HTTP 并发不受该值限制。
    concurrent_execution_db_concurrency: int = 20
    # 并发执行单批次最大允许下发的 Agent 调用数；防止误填超大并发拖垮本机或 OpenClaw。
    concurrent_execution_max_concurrency: int = 200

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
    openclaw_base_url: Optional[str] = None
    openclaw_api_key: Optional[str] = None

    model_config = {
        "env_file": ".env",
        "case_sensitive": False
    }


settings = Settings()
