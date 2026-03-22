"""比对服务"""

import time
import json
from typing import Tuple
from app.core.logger import logger
from app.core.metrics import observe_llm_compare_duration
from app.models.execution import ComparisonResult
from app.clients.llm_client import LLMClient


class ComparisonService:
    """LLM 比对服务"""

    COMPARE_PROMPT = """你是一个 AI 输出比对专家。请比对实际输出和预期结果的语义一致性。

问题：
{question}

预期结果：
{baseline}

实际输出：
{actual}

请判断：
1. 实际输出和预期结果在语义上是否一致？是否满足问题要求？
2. 给一个一致性分数 0 到 1，0 表示完全不一致，1 表示完全一致。

输出 JSON 格式：
{{
  "consistent": true/false,
  "score": 0.x,
  "reason": "简要解释为什么这么打分"
}}
"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def compare(
        self,
        question: str,
        actual: str,
        baseline: str
    ) -> ComparisonResult:
        """比对结果"""
        start_time = time.time()
        prompt = self.COMPARE_PROMPT.format(
            question=question,
            baseline=baseline,
            actual=actual
        )

        try:
            score, passed, reason = await self.llm_client.compare(
                prompt=prompt,
                actual=actual,
                baseline=baseline
            )

            duration = time.time() - start_time
            observe_llm_compare_duration(duration)
            logger.info(f"Comparison completed: score={score} passed={passed} duration={duration:.2f}s")

            return ComparisonResult(
                score=score,
                passed=passed,
                reason=reason
            )
        except Exception as e:
            duration = time.time() - start_time
            observe_llm_compare_duration(duration)
            logger.error(f"Comparison failed: {e}")
            return ComparisonResult(
                score=0.0,
                passed=False,
                reason=f"Comparison error: {str(e)}"
            )
