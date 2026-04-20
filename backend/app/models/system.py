"""系统配置模型"""

from typing import Optional
from pydantic import BaseModel, Field


class ClickHouseConfigUpdate(BaseModel):
    """更新 ClickHouse 配置请求"""

    endpoint: str = Field(..., max_length=2048)
    database: str = Field(..., max_length=255)
    username: Optional[str] = Field(None, max_length=255)
    password: Optional[str] = None
    source_type: str = Field(..., max_length=50)  # opik | langfuse


class ClickHouseConfigResponse(BaseModel):
    """ClickHouse 配置响应"""

    endpoint: str
    database: str
    username: Optional[str]
    source_type: str

    class Config:
        from_attributes = True


class ClickHouseTestResponse(BaseModel):
    """测试连接响应"""

    success: bool
    message: str


# 前端运行时配置响应，只暴露非敏感配置，避免前端硬编码后端运行参数。
class RuntimeConfigResponse(BaseModel):
    # 并发执行单批次最大 Agent 调用数；前端只用于输入限制和提示，后端仍做最终硬校验。
    concurrent_execution_max_concurrency: int
