"""Comparison service."""

import asyncio
import json
import re
import time
from datetime import UTC, datetime
from typing import Optional

import httpx
from Levenshtein import distance

from app.clients.llm_client import LLMClient
from app.core.logger import logger
from app.core.metrics import observe_llm_compare_duration
from app.domain.entities.comparison import (
    ComparisonResult as ComparisonResultEntity,
    ComparisonStatus,
)
from app.domain.entities.execution import ExecutionJob
from app.domain.entities.llm import LLMModel
from app.domain.entities.scenario import Scenario
from app.domain.entities.trace import Span
from app.domain.repositories.comparison_repo import ComparisonRepository
from app.models.execution import ComparisonResult
from app.models.llm import DEFAULT_COMPARISON_PROMPT


MAX_RETRIES = 3
MAX_CONTENT_LENGTH = 8000
ALGORITHM_PASS_THRESHOLD = 0.9


def levenshtein_similarity(a: str, b: str) -> float:
    """Return a normalized similarity score in [0, 1]."""
    edit_distance = distance(a, b)
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1 - (edit_distance / max_len)


def normalize_json_content(content: str) -> str:
    """Normalize JSON-looking content for stable comparisons."""
    if not content:
        return content

    content = re.sub(r"^```(?:json)?\n", "", content.strip())
    content = re.sub(r"\n```$", "", content)
    content = content.strip()

    if not (content.startswith("{") or content.startswith("[")):
        return content

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return content

    return json.dumps(parsed, sort_keys=True, ensure_ascii=False)


def truncate_content(content: str) -> str:
    """Trim overly long content before sending it to an LLM."""
    if len(content) <= MAX_CONTENT_LENGTH:
        return content
    return content[: MAX_CONTENT_LENGTH - 10] + "\n[...truncated]"


def calculate_algorithm_similarity(actual: str, baseline: str) -> float:
    """Run the legacy algorithm coarse screening on normalized content."""
    normalized_actual = normalize_json_content(actual)
    normalized_baseline = normalize_json_content(baseline)
    return levenshtein_similarity(normalized_actual, normalized_baseline)


def extract_llm_content(output: str) -> str:
    """Extract assistant-visible text from an LLM span output payload."""
    if not output:
        return output

    def extract_message_content(message_content: object) -> str:
        if isinstance(message_content, str):
            return message_content
        if isinstance(message_content, list):
            parts: list[str] = []
            for item in message_content:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
            return "\n".join(parts).strip()
        return ""

    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return output

    if isinstance(parsed, dict) and "assistantTexts" in parsed:
        texts = parsed["assistantTexts"]
        if isinstance(texts, list):
            return "\n".join(str(text) for text in texts if text)

    if isinstance(parsed, dict) and "lastAssistant" in parsed:
        content = parsed["lastAssistant"].get("content")
        extracted = extract_message_content(content)
        if extracted:
            return extracted

    if isinstance(parsed, dict):
        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    extracted = extract_message_content(message.get("content"))
                    if extracted:
                        return extracted
                delta = first_choice.get("delta")
                if isinstance(delta, dict):
                    extracted = extract_message_content(delta.get("content"))
                    if extracted:
                        return extracted

    if isinstance(parsed, dict) and "output_text" in parsed:
        content = parsed["output_text"]
        if isinstance(content, list):
            return "\n".join(str(item) for item in content if item).strip()
        if isinstance(content, str):
            return content

    return output


class ComparisonService:
    """LLM-only comparison service."""

    RESULT_COMPARE_PROMPT = """请判断下面【基线输出】和【实际输出】的核心语义是否一致：

基线输出:
{baseline}

实际输出:
{actual}

要求：
1. 核心语义一致时返回 consistent = true
2. 核心语义不一致时返回 consistent = false
3. 简要说明判断原因
4. 只输出 JSON：{"consistent": boolean, "reason": string, "score": number}
"""

    def __init__(self, llm_client: LLMClient, comparison_repo: Optional[ComparisonRepository] = None):
        self.llm_client = llm_client
        self.comparison_repo = comparison_repo

    @staticmethod
    def _get_comparable_llm_spans(trace_spans: list[Span]) -> list[Span]:
        """Keep only OpenAI LLM spans in the comparison flow."""
        return [
            span
            for span in trace_spans
            if (span.span_type or "").lower() == "llm" and (span.provider or "").lower() == "openai"
        ]

    async def _verify_with_llm(
        self,
        prompt: str,
        actual_output: str,
        baseline_output: str,
    ) -> tuple[bool, str]:
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                _, consistent, reason = await self.llm_client.compare(
                    prompt,
                    actual_output,
                    baseline_output,
                )
                return consistent, reason
            except Exception as exc:  # pragma: no cover - defensive retry path
                last_error = exc
                if attempt == MAX_RETRIES - 1:
                    break
                await asyncio.sleep(2**attempt)

        logger.warning("LLM verification failed after retries: %s", last_error)
        if isinstance(last_error, httpx.TimeoutException):
            return False, f"LLM 语义校验请求超时，已重试 {MAX_RETRIES} 次"
        return False, f"LLM 语义校验失败：{last_error}" if last_error else "LLM 语义校验失败"

    async def detailed_compare(
        self,
        scenario: Scenario,
        execution: ExecutionJob,
        trace_spans: list[Span],
        llm_model: LLMModel,
    ) -> ComparisonResultEntity:
        """Run the LLM-only replay comparison flow."""
        llm_spans = self._get_comparable_llm_spans(trace_spans)
        actual_count = len(llm_spans)

        expected_min = scenario.llm_count_min or 0
        expected_max = scenario.llm_count_max if scenario.llm_count_max is not None else expected_min
        invalid_range = expected_min < 0 or expected_max < 0 or expected_min > expected_max
        count_passed = False if invalid_range else expected_min <= actual_count <= expected_max

        llm_count_check = {
            "expected_min": expected_min,
            "expected_max": expected_max,
            "actual_count": actual_count,
            "passed": count_passed,
        }

        baseline_output = (scenario.baseline_result or "").strip()
        actual_output = extract_llm_content(llm_spans[-1].output or "").strip() if llm_spans else ""
        final_output_comparison = {
            "baseline_output": baseline_output,
            "actual_output": actual_output,
            "consistent": False,
            "reason": "",
            "algorithm_similarity": None,
            "verification_mode": None,
        }

        error_message: str | None = None
        if invalid_range:
            error_message = "场景配置的 LLM 调用次数范围无效"
            final_output_comparison["reason"] = error_message
        elif not count_passed:
            final_output_comparison["reason"] = (
                f"LLM 调用次数不符合预期，实际为 {actual_count} 次，"
                f"期望范围为 {expected_min} ~ {expected_max} 次"
            )
        elif not baseline_output:
            final_output_comparison["reason"] = "场景基线输出为空"
        elif not actual_output:
            final_output_comparison["reason"] = "Trace 中没有找到最终 LLM 输出"
        else:
            similarity = calculate_algorithm_similarity(actual_output, baseline_output)
            final_output_comparison["algorithm_similarity"] = similarity

            if similarity >= ALGORITHM_PASS_THRESHOLD:
                final_output_comparison["consistent"] = True
                final_output_comparison["verification_mode"] = "algorithm_short_circuit"
                final_output_comparison["reason"] = (
                    f"算法粗筛相似度为 {similarity:.3f}，达到直通阈值，已跳过 LLM 语义校验。"
                )
            else:
                prompt_template = (llm_model.comparison_prompt or DEFAULT_COMPARISON_PROMPT).strip()
                prompt = prompt_template.replace("{{baseline_result}}", baseline_output)
                prompt = prompt.replace("{{actual_result}}", actual_output)

                started_at = time.time()
                consistent, reason = await self._verify_with_llm(
                    prompt,
                    actual_output,
                    baseline_output,
                )
                observe_llm_compare_duration(time.time() - started_at)
                final_output_comparison["consistent"] = consistent
                final_output_comparison["verification_mode"] = (
                    "llm_verification" if consistent or not reason.startswith("LLM 语义校验") else "llm_verification_error"
                )
                final_output_comparison["reason"] = reason

        return ComparisonResultEntity(
            execution_id=execution.id,
            scenario_id=scenario.id,
            trace_id=execution.trace_id,
            process_score=None,
            result_score=None,
            overall_passed=count_passed and final_output_comparison["consistent"],
            details_json=json.dumps(
                {
                    "tool_comparisons": [],
                    "llm_comparison": None,
                    "llm_count_check": llm_count_check,
                    "final_output_comparison": final_output_comparison,
                },
                ensure_ascii=False,
            ),
            status=ComparisonStatus.COMPLETED,
            error_message=error_message,
            retry_count=0,
            completed_at=datetime.now(UTC),
        )

    async def compare(self, question: str, actual: str, baseline: str) -> ComparisonResult:
        """Backward-compatible single-result comparison entrypoint."""
        del question

        prompt = self.RESULT_COMPARE_PROMPT.format(
            baseline=truncate_content(normalize_json_content(baseline)),
            actual=truncate_content(normalize_json_content(extract_llm_content(actual))),
        )

        started_at = time.time()
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                score, passed, reason = await self.llm_client.compare(prompt, actual, baseline)
                observe_llm_compare_duration(time.time() - started_at)
                logger.info(
                    "Comparison completed: score=%s passed=%s duration=%.2fs",
                    score,
                    passed,
                    time.time() - started_at,
                )
                return ComparisonResult(
                    score=max(0.0, min(1.0, float(score))),
                    passed=bool(passed),
                    reason=str(reason or "LLM verification completed"),
                )
            except Exception as exc:  # pragma: no cover - defensive retry path
                last_error = exc
                if attempt == MAX_RETRIES - 1:
                    break
                await asyncio.sleep(2**attempt)

        observe_llm_compare_duration(time.time() - started_at)
        logger.error("Comparison failed after retries: %s", last_error)
        return ComparisonResult(
            score=0.0,
            passed=False,
            reason=f"Comparison error: {last_error}" if last_error else "Comparison failed",
        )
