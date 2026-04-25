"""场景请求与响应模型。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScenarioCreate(BaseModel):
    """定义创建 Case 的请求体，要求一次提交完整的 Agent 绑定集合。"""

    agent_ids: list[UUID] = Field(..., min_length=1)
    name: str = Field(..., max_length=255)
    description: str | None = None
    prompt: str = Field(...)
    baseline_result: str = Field(...)
    llm_count_min: int = Field(default=0, ge=0)
    llm_count_max: int = Field(default=999, ge=0)
    compare_enabled: bool = True

    @model_validator(mode="after")
    def validate_request(self) -> "ScenarioCreate":
        """校验 LLM 调用范围上下界，避免创建后出现无法执行的非法规则。"""

        if self.llm_count_min > self.llm_count_max:
            raise ValueError("llm_count_min must be less than or equal to llm_count_max")
        return self


class ScenarioUpdate(BaseModel):
    """定义编辑 Case 的请求体，支持整体替换 Agent 绑定集合。"""

    agent_ids: list[UUID] | None = Field(default=None, min_length=1)
    name: str | None = Field(None, max_length=255)
    description: str | None = None
    prompt: str | None = None
    baseline_result: str | None = None
    llm_count_min: int | None = Field(default=None, ge=0)
    llm_count_max: int | None = Field(default=None, ge=0)
    compare_enabled: bool | None = None

    @model_validator(mode="after")
    def validate_llm_count_range(self) -> "ScenarioUpdate":
        """校验局部更新时的上下界组合，避免保存出互相冲突的规则。"""

        if (
            self.llm_count_min is not None
            and self.llm_count_max is not None
            and self.llm_count_min > self.llm_count_max
        ):
            raise ValueError("llm_count_min must be less than or equal to llm_count_max")
        return self


class ScenarioResponse(BaseModel):
    """定义 Case 统一响应结构，返回主记录与多 Agent 展示信息。"""

    id: UUID
    agent_ids: list[UUID]
    agent_names: list[str]
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
