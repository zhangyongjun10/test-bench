"""LLM 模型"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_COMPARISON_PROMPT = """请判断下面【基线输出】和【实际输出】的核心语义是否一致：

基线输出:
{{baseline_result}}

实际输出:
{{actual_result}}

要求：
1. 核心语义一致（回答结论相同、解决同一个问题、满足相同需求）时返回 consistent = true
2. 核心语义不一致时返回 consistent = false
3. 简要说明判断原因
4. 只输出 JSON：{"consistent": boolean, "reason": string}
"""


class LLMCreate(BaseModel):
    """创建 LLM 请求"""

    name: str = Field(..., max_length=255)
    provider: str = Field(..., max_length=50)
    model_id: str = Field(..., max_length=255)
    base_url: str | None = Field(None, max_length=2048)
    api_key: str = Field(...)
    temperature: float = 0.0
    max_tokens: int = 1024
    comparison_prompt: str | None = None


class LLMUpdate(BaseModel):
    """更新 LLM 请求"""

    name: str | None = Field(None, max_length=255)
    provider: str | None = Field(None, max_length=50)
    model_id: str | None = Field(None, max_length=255)
    base_url: str | None = Field(None, max_length=2048)
    api_key: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    comparison_prompt: str | None = None


class LLMResponse(BaseModel):
    """LLM 响应"""

    id: UUID
    name: str
    provider: str
    model_id: str
    base_url: str | None
    temperature: float
    max_tokens: int
    comparison_prompt: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LLMTestResponse(BaseModel):
    """测试连接响应"""

    success: bool
    message: str
