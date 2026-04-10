"""场景模型"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScenarioCreate(BaseModel):
    """创建场景请求"""

    agent_id: UUID
    name: str = Field(..., max_length=255)
    description: str | None = None
    prompt: str = Field(...)
    baseline_result: str | None = None
    llm_count_min: int = Field(default=0, ge=0)
    llm_count_max: int = Field(default=999, ge=0)
    compare_enabled: bool = True

    @model_validator(mode="after")
    def validate_llm_count_range(self) -> "ScenarioCreate":
        if self.llm_count_min > self.llm_count_max:
            raise ValueError("llm_count_min must be less than or equal to llm_count_max")
        return self


class ScenarioUpdate(BaseModel):
    """更新场景请求"""

    agent_id: UUID | None = None
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    prompt: str | None = None
    baseline_result: str | None = None
    llm_count_min: int | None = Field(default=None, ge=0)
    llm_count_max: int | None = Field(default=None, ge=0)
    compare_enabled: bool | None = None

    @model_validator(mode="after")
    def validate_llm_count_range(self) -> "ScenarioUpdate":
        if (
            self.llm_count_min is not None
            and self.llm_count_max is not None
            and self.llm_count_min > self.llm_count_max
        ):
            raise ValueError("llm_count_min must be less than or equal to llm_count_max")
        return self


class ScenarioResponse(BaseModel):
    """场景响应"""

    id: UUID
    agent_id: UUID
    agent_name: str | None = None
    name: str
    description: str | None
    prompt: str
    baseline_result: str | None
    llm_count_min: int
    llm_count_max: int
    compare_enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
