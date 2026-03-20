"""LLM 模型"""

from uuid import UUID
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class LLMCreate(BaseModel):
    """创建 LLM 请求"""

    name: str = Field(..., max_length=255)
    provider: str = Field(..., max_length=50)
    model_id: str = Field(..., max_length=255)
    base_url: Optional[str] = Field(None, max_length=2048)
    api_key: str = Field(...)
    temperature: float = 0.0
    max_tokens: int = 1024
    is_default: bool = False


class LLMUpdate(BaseModel):
    """更新 LLM 请求"""

    name: Optional[str] = Field(None, max_length=255)
    provider: Optional[str] = Field(None, max_length=50)
    model_id: Optional[str] = Field(None, max_length=255)
    base_url: Optional[str] = Field(None, max_length=2048)
    api_key: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    is_default: Optional[bool] = None


class LLMResponse(BaseModel):
    """LLM 响应"""

    id: UUID
    name: str
    provider: str
    model_id: str
    base_url: Optional[str]
    temperature: float
    max_tokens: int
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LLMTestResponse(BaseModel):
    """测试连接响应"""

    success: bool
    message: str
