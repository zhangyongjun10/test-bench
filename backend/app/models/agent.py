"""Agent 模型"""

from uuid import UUID
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    """创建 Agent 请求"""

    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    base_url: str = Field(..., max_length=2048)
    api_key: str = Field(...)
    user_session: Optional[str] = Field(None, max_length=255)


class AgentUpdate(BaseModel):
    """更新 Agent 请求"""

    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    base_url: Optional[str] = Field(None, max_length=2048)
    api_key: Optional[str] = None
    user_session: Optional[str] = Field(None, max_length=255)


class AgentResponse(BaseModel):
    """Agent 响应"""

    id: UUID
    name: str
    description: Optional[str]
    base_url: str
    user_session: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentTestResponse(BaseModel):
    """测试连接响应"""

    success: bool
    message: str
