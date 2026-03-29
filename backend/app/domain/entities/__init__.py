"""领域实体"""

from app.domain.entities.agent import Agent
from app.domain.entities.scenario import Scenario
from app.domain.entities.execution import ExecutionJob, ExecutionStatus
from app.domain.entities.llm import LLMModel
from app.domain.entities.system import SystemClickhouseConfig
from app.domain.entities.comparison import ComparisonResult, ComparisonStatus

__all__ = [
    "Agent",
    "Scenario",
    "ExecutionJob",
    "ExecutionStatus",
    "LLMModel",
    "SystemClickhouseConfig",
    "ComparisonResult",
    "ComparisonStatus",
]

