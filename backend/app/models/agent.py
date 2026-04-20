"""Agent 模型"""

from uuid import UUID
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# 创建 Agent 的 API 入参；Agent 只保存连接信息，不再承载用户 Session，会话隔离由 execution 负责。
class AgentCreate(BaseModel):
    """创建 Agent 请求"""

    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    base_url: str = Field(..., max_length=2048)
    api_key: str = Field(...)


# 更新 Agent 的 API 入参；未传字段保持原值，且不允许通过 Agent 配置修改运行会话。
class AgentUpdate(BaseModel):
    """更新 Agent 请求"""

    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    base_url: Optional[str] = Field(None, max_length=2048)
    api_key: Optional[str] = None


# Agent 的 API 响应模型；只暴露连接配置元信息，避免前端继续依赖 Agent 级 Session。
class AgentResponse(BaseModel):
    """Agent 响应"""

    id: UUID
    name: str
    description: Optional[str]
    base_url: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentTestResponse(BaseModel):
    """测试连接响应"""

    success: bool
    message: str
