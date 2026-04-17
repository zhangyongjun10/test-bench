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
from app.domain.entities.comparison import ComparisonResult as ComparisonResultEntity, ComparisonStatus
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
    edit_distance = distance(a, b)
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1 - (edit_distance / max_len)


def normalize_json_content(content: str) -> str:
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
    if len(content) <= MAX_CONTENT_LENGTH:
        return content
    return content[: MAX_CONTENT_LENGTH - 10] + "\n[...truncated]"


def calculate_algorithm_similarity(actual: str, baseline: str) -> float:
    return levenshtein_similarity(normalize_json_content(actual), normalize_json_content(baseline))


def extract_llm_content(output: str) -> str:
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

    if isinstance(parsed, dict) and "assistantTexts" in parsed and isinstance(parsed["assistantTexts"], list):
        return "\n".join(str(text) for text in parsed["assistantTexts"] if text)

    if isinstance(parsed, dict) and "lastAssistant" in parsed:
        return extract_message_content(parsed["lastAssistant"].get("content"))

    if isinstance(parsed, dict):
        choices = parsed.get("choices")
        if isinstance(choices, list):
            parts: list[str] = []
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict):
                    extracted = extract_message_content(message.get("content"))
                    if extracted:
                        parts.append(extracted)
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    extracted = extract_message_content(delta.get("content"))
                    if extracted:
                        parts.append(extracted)
            return "\n".join(parts).strip()

    if isinstance(parsed, dict) and "output_text" in parsed:
        content = parsed["output_text"]
        if isinstance(content, list):
            return "\n".join(str(item) for item in content if item).strip()
        if isinstance(content, str):
            return content

    return output


def has_tool_call_output(output: str) -> bool:
    if not output:
        return False
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    choices = parsed.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict) and (message.get("tool_calls") or message.get("function_call")):
            return True
        delta = choice.get("delta")
        if isinstance(delta, dict) and (delta.get("tool_calls") or delta.get("function_call")):
            return True
    return False


def extract_final_llm_content(llm_spans: list[Span]) -> str:
    if not llm_spans:
        return ""
    output = llm_spans[-1].output or ""
    if has_tool_call_output(output):
        return ""
    return extract_llm_content(output).strip()


class ComparisonService:
    """LLM-only comparison service."""

    RESULT_COMPARE_PROMPT = """Compare whether the baseline output and actual output are semantically consistent.

Baseline:
{baseline}

Actual:
{actual}

Return JSON only: {"consistent": boolean, "reason": string, "score": number}
"""

    def __init__(self, llm_client: LLMClient, comparison_repo: Optional[ComparisonRepository] = None):
        self.llm_client = llm_client
        self.comparison_repo = comparison_repo

    @staticmethod
    def _get_comparable_llm_spans(trace_spans: list[Span]) -> list[Span]:
        llm_spans = [span for span in trace_spans if (span.span_type or "").lower() == "llm"]
        openai_spans = [span for span in llm_spans if (span.provider or "").lower() == "openai"]
        return openai_spans or llm_spans

    async def _verify_with_llm(self, prompt: str, actual_output: str, baseline_output: str) -> tuple[bool, str]:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                _, consistent, reason = await self.llm_client.compare(prompt, actual_output, baseline_output)
                return consistent, reason
            except Exception as exc:
                last_error = exc
                if attempt == MAX_RETRIES - 1:
                    break
                await asyncio.sleep(2**attempt)
        logger.warning("LLM verification failed after retries: %s", last_error)
        if isinstance(last_error, httpx.TimeoutException):
            return False, f"LLM verification timed out after {MAX_RETRIES} retries"
        return False, f"LLM verification failed: {last_error}" if last_error else "LLM verification failed"

    # 记录最终发送给比对模型的请求内容，方便排查 actual_output 是否来自最终 LLM span 或 original_response fallback。
    @staticmethod
    def _log_llm_verification_request(
        *,
        execution: ExecutionJob,
        llm_model: LLMModel,
        prompt: str,
        actual_output: str,
        baseline_output: str,
        source_type: str,
    ) -> None:
        logger.info(
            "LLM comparison request payload",
            execution_id=str(execution.id),
            trace_id=execution.trace_id,
            source_type=source_type,
            llm_model_id=str(llm_model.id),
            llm_model_name=llm_model.name,
            llm_model_provider=llm_model.provider,
            llm_model_model_id=llm_model.model_id,
            baseline_output_length=len(baseline_output),
            actual_output_length=len(actual_output),
            prompt=prompt,
            baseline_output=baseline_output,
            actual_output=actual_output,
        )

    # 记录比对模型返回结果，与请求日志通过 execution_id、trace_id 和 task_id 关联。
    @staticmethod
    def _log_llm_verification_response(
        *,
        execution: ExecutionJob,
        llm_model: LLMModel,
        consistent: bool,
        reason: str,
        duration_ms: float,
        source_type: str,
    ) -> None:
        logger.info(
            "LLM comparison response payload",
            execution_id=str(execution.id),
            trace_id=execution.trace_id,
            source_type=source_type,
            llm_model_id=str(llm_model.id),
            llm_model_name=llm_model.name,
            llm_model_provider=llm_model.provider,
            llm_model_model_id=llm_model.model_id,
            consistent=consistent,
            reason=reason,
            duration_ms=round(duration_ms, 2),
        )

    # 执行场景与基线的自动/重新比对，LLM 次数只统计 provider=openai 的 LLM span，最终输出允许 fallback 到 original_response。
    async def detailed_compare(
        self,
        scenario: Scenario,
        execution: ExecutionJob,
        trace_spans: list[Span],
        llm_model: LLMModel,
    ) -> ComparisonResultEntity:
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
        actual_output = extract_final_llm_content(llm_spans) or (execution.original_response or "").strip()
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
            error_message = "LLM 调用次数范围配置无效"
            final_output_comparison["reason"] = error_message
        elif not count_passed:
            final_output_comparison["reason"] = (
                f"LLM 调用次数不符合预期，实际为 {actual_count} 次，期望范围为 {expected_min} ~ {expected_max} 次"
            )
        elif not baseline_output:
            final_output_comparison["reason"] = "场景基线输出为空"
        elif not actual_output:
            final_output_comparison["reason"] = "未找到最终 LLM 输出"
        else:
            similarity = calculate_algorithm_similarity(actual_output, baseline_output)
            final_output_comparison["algorithm_similarity"] = similarity
            if similarity >= ALGORITHM_PASS_THRESHOLD:
                final_output_comparison["consistent"] = True
                final_output_comparison["verification_mode"] = "algorithm_short_circuit"
                final_output_comparison["reason"] = f"Algorithm similarity {similarity:.3f} passed the shortcut threshold"
            else:
                prompt_template = (llm_model.comparison_prompt or DEFAULT_COMPARISON_PROMPT).strip()
                prompt = prompt_template.replace("{{baseline_result}}", baseline_output)
                prompt = prompt.replace("{{actual_result}}", actual_output)
                self._log_llm_verification_request(
                    execution=execution,
                    llm_model=llm_model,
                    prompt=prompt,
                    actual_output=actual_output,
                    baseline_output=baseline_output,
                    source_type="execution",
                )
                started_at = time.time()
                consistent, reason = await self._verify_with_llm(prompt, actual_output, baseline_output)
                duration_seconds = time.time() - started_at
                observe_llm_compare_duration(duration_seconds)
                self._log_llm_verification_response(
                    execution=execution,
                    llm_model=llm_model,
                    consistent=consistent,
                    reason=reason,
                    duration_ms=duration_seconds * 1000,
                    source_type="execution",
                )
                final_output_comparison["consistent"] = consistent
                final_output_comparison["verification_mode"] = (
                    "llm_verification" if consistent or not reason.startswith("LLM verification") else "llm_verification_error"
                )
                final_output_comparison["reason"] = reason

        return ComparisonResultEntity(
            execution_id=execution.id,
            scenario_id=scenario.id,
            llm_model_id=llm_model.id,
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

    # 执行回放或指定基线比对，基线由调用方传入，实际输出仍按最终 OpenAI LLM span 优先、original_response 兜底。
    async def detailed_compare_with_baseline(
        self,
        *,
        scenario: Scenario,
        execution: ExecutionJob,
        trace_spans: list[Span],
        llm_model: LLMModel,
        baseline_output: str,
        expected_min: int,
        expected_max: int,
        source_type: str = "replay",
        replay_task_id: object | None = None,
        baseline_source: str | None = None,
    ) -> ComparisonResultEntity:
        llm_spans = self._get_comparable_llm_spans(trace_spans)
        actual_count = len(llm_spans)
        invalid_range = expected_min < 0 or expected_max < 0 or expected_min > expected_max
        count_passed = False if invalid_range else expected_min <= actual_count <= expected_max
        llm_count_check = {
            "expected_min": expected_min,
            "expected_max": expected_max,
            "actual_count": actual_count,
            "passed": count_passed,
        }

        actual_output = extract_final_llm_content(llm_spans) or (execution.original_response or "").strip()
        final_output_comparison = {
            "baseline_output": (baseline_output or "").strip(),
            "actual_output": actual_output,
            "consistent": False,
            "reason": "",
            "algorithm_similarity": None,
            "verification_mode": None,
        }

        error_message: str | None = None
        if invalid_range:
            error_message = "LLM 调用次数范围配置无效"
            final_output_comparison["reason"] = error_message
        elif not count_passed:
            final_output_comparison["reason"] = (
                f"LLM 调用次数不符合预期，实际为 {actual_count} 次，期望范围为 {expected_min} ~ {expected_max} 次"
            )
        elif not final_output_comparison["baseline_output"]:
            final_output_comparison["reason"] = "基线输出为空"
        elif not actual_output:
            final_output_comparison["reason"] = "未找到最终 LLM 输出"
        else:
            similarity = calculate_algorithm_similarity(actual_output, final_output_comparison["baseline_output"])
            final_output_comparison["algorithm_similarity"] = similarity
            if similarity >= ALGORITHM_PASS_THRESHOLD:
                final_output_comparison["consistent"] = True
                final_output_comparison["verification_mode"] = "algorithm_short_circuit"
                final_output_comparison["reason"] = f"Algorithm similarity {similarity:.3f} passed the shortcut threshold"
            else:
                prompt_template = (llm_model.comparison_prompt or DEFAULT_COMPARISON_PROMPT).strip()
                prompt = prompt_template.replace("{{baseline_result}}", final_output_comparison["baseline_output"])
                prompt = prompt.replace("{{actual_result}}", actual_output)
                self._log_llm_verification_request(
                    execution=execution,
                    llm_model=llm_model,
                    prompt=prompt,
                    actual_output=actual_output,
                    baseline_output=final_output_comparison["baseline_output"],
                    source_type=source_type,
                )
                started_at = time.time()
                consistent, reason = await self._verify_with_llm(prompt, actual_output, final_output_comparison["baseline_output"])
                duration_seconds = time.time() - started_at
                observe_llm_compare_duration(duration_seconds)
                self._log_llm_verification_response(
                    execution=execution,
                    llm_model=llm_model,
                    consistent=consistent,
                    reason=reason,
                    duration_ms=duration_seconds * 1000,
                    source_type=source_type,
                )
                final_output_comparison["consistent"] = consistent
                final_output_comparison["verification_mode"] = (
                    "llm_verification" if consistent or not reason.startswith("LLM verification") else "llm_verification_error"
                )
                final_output_comparison["reason"] = reason

        return ComparisonResultEntity(
            execution_id=execution.id,
            scenario_id=scenario.id,
            llm_model_id=llm_model.id,
            replay_task_id=replay_task_id,
            source_type=source_type,
            baseline_source=baseline_source,
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
                logger.info("Comparison completed: score=%s passed=%s duration=%.2fs", score, passed, time.time() - started_at)
                return ComparisonResult(score=max(0.0, min(1.0, float(score))), passed=bool(passed), reason=str(reason or "LLM verification completed"))
            except Exception as exc:
                last_error = exc
                if attempt == MAX_RETRIES - 1:
                    break
                await asyncio.sleep(2**attempt)
        observe_llm_compare_duration(time.time() - started_at)
        logger.error("Comparison failed after retries: %s", last_error)
        return ComparisonResult(score=0.0, passed=False, reason=f"Comparison error: {last_error}" if last_error else "Comparison failed")
