import json
import uuid

import httpx
import pytest

from app.domain.entities.execution import ExecutionJob
from app.domain.entities.llm import LLMModel
from app.domain.entities.scenario import Scenario
from app.domain.entities.trace import Span, SpanMetrics
from app.services.comparison import ComparisonService, extract_llm_content


class FakeLLMClient:
    def __init__(self, consistent: bool = True, reason: str = "ok"):
        self.consistent = consistent
        self.reason = reason
        self.prompts: list[str] = []

    async def test_connection(self, model: LLMModel) -> tuple[bool, str]:
        return True, "ok"

    async def compare(self, prompt: str, actual: str, baseline: str) -> tuple[float, bool, str]:
        self.prompts.append(prompt)
        return 0.0, self.consistent, self.reason


class TimeoutLLMClient(FakeLLMClient):
    async def compare(self, prompt: str, actual: str, baseline: str) -> tuple[float, bool, str]:
        del prompt, actual, baseline
        raise httpx.ReadTimeout("timed out")


def make_llm_span(output: str) -> Span:
    return Span(
        span_id="span-1",
        trace_id="trace-1",
        span_type="llm",
        name="assistant",
        provider="openai",
        input="input",
        output=output,
        start_time_ms=0,
        end_time_ms=1,
        duration_ms=1,
        metrics=SpanMetrics(),
    )


def make_other_provider_llm_span(output: str) -> Span:
    return Span(
        span_id="span-other",
        trace_id="trace-1",
        span_type="llm",
        name="assistant-other",
        provider="anthropic",
        input="input",
        output=output,
        start_time_ms=0,
        end_time_ms=1,
        duration_ms=1,
        metrics=SpanMetrics(),
    )


def make_execution() -> ExecutionJob:
    return ExecutionJob(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        scenario_id=uuid.uuid4(),
        llm_model_id=uuid.uuid4(),
        trace_id="trace-1",
        status="completed",
    )


def make_model(prompt: str = "compare {{baseline_result}} vs {{actual_result}}") -> LLMModel:
    return LLMModel(
        id=uuid.uuid4(),
        name="compare-model",
        provider="openai",
        model_id="gpt-test",
        api_key_encrypted="secret",
        comparison_prompt=prompt,
    )


def test_extract_llm_content_ignores_openai_tool_call_only_output():
    output = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "read",
                                    "arguments": '{"path":"/app/skills/weather/SKILL.md"}',
                                }
                            }
                        ],
                    }
                }
            ]
        },
        ensure_ascii=False,
    )

    assert extract_llm_content(output) == ""


@pytest.mark.asyncio
async def test_detailed_compare_fails_when_llm_count_out_of_range():
    scenario = Scenario(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        name="scenario",
        prompt="prompt",
        baseline_result="baseline",
        llm_count_min=2,
        llm_count_max=3,
        compare_enabled=True,
    )
    execution = make_execution()
    client = FakeLLMClient()
    service = ComparisonService(client)

    result = await service.detailed_compare(
        scenario=scenario,
        execution=execution,
        trace_spans=[make_llm_span("actual")],
        llm_model=make_model(),
    )

    details = json.loads(result.details_json)
    assert result.overall_passed is False
    assert details["llm_count_check"]["passed"] is False
    assert "LLM" in details["final_output_comparison"]["reason"]
    assert client.prompts == []


@pytest.mark.asyncio
async def test_detailed_compare_uses_llm_model_prompt_for_final_output_check():
    scenario = Scenario(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        name="scenario",
        prompt="prompt",
        baseline_result="baseline answer",
        llm_count_min=1,
        llm_count_max=2,
        compare_enabled=True,
    )
    execution = make_execution()
    client = FakeLLMClient(consistent=True, reason="same meaning")
    service = ComparisonService(client)
    llm_model = make_model(prompt="judge: {{baseline_result}} || {{actual_result}}")

    result = await service.detailed_compare(
        scenario=scenario,
        execution=execution,
        trace_spans=[make_llm_span('{"assistantTexts":["actual answer"]}')],
        llm_model=llm_model,
    )

    details = json.loads(result.details_json)
    assert result.overall_passed is True
    assert details["llm_count_check"]["passed"] is True
    assert details["final_output_comparison"]["consistent"] is True
    assert details["final_output_comparison"]["reason"] == "same meaning"
    assert details["final_output_comparison"]["algorithm_similarity"] is not None
    assert details["final_output_comparison"]["verification_mode"] == "llm_verification"
    assert client.prompts == ["judge: baseline answer || actual answer"]


@pytest.mark.asyncio
async def test_detailed_compare_short_circuits_on_high_algorithm_similarity():
    scenario = Scenario(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        name="scenario",
        prompt="prompt",
        baseline_result='{"answer":"hello","items":[1,2]}',
        llm_count_min=1,
        llm_count_max=2,
        compare_enabled=True,
    )
    execution = make_execution()
    client = FakeLLMClient(consistent=False, reason="should not be used")
    service = ComparisonService(client)

    result = await service.detailed_compare(
        scenario=scenario,
        execution=execution,
        trace_spans=[make_llm_span('{"answer":"hello","items":[1,2]}')],
        llm_model=make_model(),
    )

    details = json.loads(result.details_json)
    assert result.overall_passed is True
    assert details["final_output_comparison"]["consistent"] is True
    assert details["final_output_comparison"]["verification_mode"] == "algorithm_short_circuit"
    assert details["final_output_comparison"]["algorithm_similarity"] == 1.0
    assert client.prompts == []


@pytest.mark.asyncio
async def test_detailed_compare_extracts_openai_style_message_content():
    scenario = Scenario(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        name="scenario",
        prompt="prompt",
        baseline_result="hello",
        llm_count_min=1,
        llm_count_max=2,
        compare_enabled=True,
    )
    execution = make_execution()
    client = FakeLLMClient(consistent=True, reason="same meaning")
    service = ComparisonService(client)

    result = await service.detailed_compare(
        scenario=scenario,
        execution=execution,
        trace_spans=[
            make_llm_span(
                json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "hello",
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            )
        ],
        llm_model=make_model(),
    )

    details = json.loads(result.details_json)
    assert details["final_output_comparison"]["actual_output"] == "hello"
    assert result.overall_passed is True


@pytest.mark.asyncio
async def test_detailed_compare_only_uses_openai_provider_llm_spans():
    scenario = Scenario(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        name="scenario",
        prompt="prompt",
        baseline_result="openai final",
        llm_count_min=2,
        llm_count_max=2,
        compare_enabled=True,
    )
    execution = make_execution()
    client = FakeLLMClient(consistent=True, reason="same meaning")
    service = ComparisonService(client)

    result = await service.detailed_compare(
        scenario=scenario,
        execution=execution,
        trace_spans=[
            make_llm_span('{"assistantTexts":["intermediate openai"]}'),
            make_other_provider_llm_span('{"assistantTexts":["should be ignored"]}'),
            make_llm_span('{"assistantTexts":["openai final"]}'),
        ],
        llm_model=make_model(),
    )

    details = json.loads(result.details_json)
    assert details["llm_count_check"]["actual_count"] == 2
    assert details["llm_count_check"]["passed"] is True
    assert details["final_output_comparison"]["actual_output"] == "openai final"


@pytest.mark.asyncio
async def test_detailed_compare_handles_llm_timeout_without_failing_recompare():
    scenario = Scenario(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        name="scenario",
        prompt="prompt",
        baseline_result="baseline answer",
        llm_count_min=1,
        llm_count_max=1,
        compare_enabled=True,
    )
    execution = make_execution()
    service = ComparisonService(TimeoutLLMClient())

    result = await service.detailed_compare(
        scenario=scenario,
        execution=execution,
        trace_spans=[make_llm_span('{"assistantTexts":["actual answer"]}')],
        llm_model=make_model(),
    )

    details = json.loads(result.details_json)
    assert result.status == "completed"
    assert result.overall_passed is False
    assert details["final_output_comparison"]["consistent"] is False
    assert details["final_output_comparison"]["verification_mode"] == "llm_verification_error"
    assert "超时" in details["final_output_comparison"]["reason"]
