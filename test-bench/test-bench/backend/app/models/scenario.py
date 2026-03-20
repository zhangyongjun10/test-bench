"""场景模型"""

from uuid import UUID
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ScenarioCreate(BaseModel):
    """创建场景请求"""

    agent_id: UUID
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    prompt: str = Field(...)
    baseline_result: Optional[str] = None
    compare_result: bool = True
    compare_process: bool = False


class ScenarioUpdate(BaseModel):
    """更新场景请求"""

    agent_id: Optional[UUID] = None
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    prompt: Optional[str] = None
    baseline_result: Optional[str] = None
    compare_result: Optional[bool] = None
    compare_process: Optional[bool] = None


class ScenarioResponse(BaseModel):
    """场景响应"""

    id: UUID
    agent_id: UUID
    name: str
    description: Optional[str]
    prompt: str
    baseline_result: Optional[str]
    compare_result: bool
    compare_process: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
