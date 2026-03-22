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
