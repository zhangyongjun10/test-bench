"""比对结果模型"""

from uuid import UUID
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


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


class DetailedComparisonResponse(BaseModel):
    """详细比对结果响应"""

    id: UUID
    execution_id: UUID
    scenario_id: UUID
    trace_id: Optional[str]
    process_score: Optional[float]  # 0-100
    result_score: Optional[float]  # 0-100
    overall_passed: bool
    tool_comparisons: List[SingleToolComparison]
    llm_comparison: Optional[SingleLLMComparison]
    status: str  # pending/processing/completed/failed
    error_message: Optional[str]
    retry_count: int
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class RecompareResponse(BaseModel):
    """重新比对响应"""

    success: bool
    message: str
