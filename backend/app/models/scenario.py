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
    baseline_tool_calls: Optional[str] = None
    baseline_result: Optional[str] = None
    compare_result: bool = True
    compare_process: bool = False
    process_threshold: float = 60.0
    result_threshold: float = 60.0
    tool_count_tolerance: int = 0
    compare_enabled: bool = True
    enable_llm_verification: bool = True


class ScenarioUpdate(BaseModel):
    """更新场景请求"""

    agent_id: Optional[UUID] = None
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    prompt: Optional[str] = None
    baseline_tool_calls: Optional[str] = None
    baseline_result: Optional[str] = None
    compare_result: Optional[bool] = None
    compare_process: Optional[bool] = None
    process_threshold: Optional[float] = None
    result_threshold: Optional[float] = None
    tool_count_tolerance: Optional[int] = None
    compare_enabled: Optional[bool] = None
    enable_llm_verification: Optional[bool] = None


class ScenarioResponse(BaseModel):
    """场景响应"""

    id: UUID
    agent_id: UUID
    agent_name: Optional[str] = None
    name: str
    description: Optional[str]
    prompt: str
    baseline_tool_calls: Optional[str]
    baseline_result: Optional[str]
    compare_result: bool
    compare_process: bool
    process_threshold: float
    result_threshold: float
    tool_count_tolerance: int
    compare_enabled: bool
    enable_llm_verification: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
