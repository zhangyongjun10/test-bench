"""比对结果模型"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SingleToolComparison(BaseModel):
    """单个 Tool 比对结果"""

    tool_name: str
    baseline_input: str
    baseline_output: str
    actual_input: str
    actual_output: str
    similarity: float  # 0-1 算法相似度
    score: float       # 0-1 最终得分
    consistent: bool
    reason: str
    matched: bool


class SingleLLMComparison(BaseModel):
    """单个 LLM 比对结果"""

    baseline_output: str
    actual_output: str
    similarity: float  # 0-1 算法相似度
    score: float       # 0-1 最终得分
    consistent: bool
    reason: str


class LLMCountCheck(BaseModel):
    """LLM count range validation result."""

    expected_min: int
    expected_max: int
    actual_count: int
    passed: bool


class FinalOutputComparison(BaseModel):
    """Final output comparison result."""

    baseline_output: str
    actual_output: str
    consistent: bool
    reason: str
    algorithm_similarity: float | None = None
    verification_mode: str | None = None


class DetailedComparisonResponse(BaseModel):
    """详细比对结果响应"""

    id: UUID
    execution_id: UUID
    scenario_id: UUID
    trace_id: str | None
    process_score: float | None  # 0-100
    result_score: float | None  # 0-100
    overall_passed: bool | None
    tool_comparisons: list[SingleToolComparison] = Field(default_factory=list)
    llm_comparison: SingleLLMComparison | None = None
    llm_count_check: LLMCountCheck | None = None
    final_output_comparison: FinalOutputComparison | None = None
    status: str  # pending/processing/completed/failed
    error_message: str | None
    retry_count: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class RecompareResponse(BaseModel):
    """重新比对响应"""

    success: bool
    message: str
