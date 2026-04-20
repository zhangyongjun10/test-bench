import uuid
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from app.clients.http_agent_client import HTTPAgentClient
from app.clients.http_agent_client import _format_exception_message
from app.models.execution import CreateExecutionRequest
from app.services import execution_service as execution_service_module
from app.services.execution_service import (
    count_openai_llm_spans,
    has_comparable_llm_output,
    has_final_openai_llm_output,
    is_trace_ready_for_comparison,
)


# 验证 Agent 请求体默认使用 openclaw:main，并从 execution 级会话注入 user 字段。
def test_http_agent_client_builds_openclaw_payload_with_user():
    client = HTTPAgentClient(
        base_url="https://agent.example.com/chat",
        api_key="secret",
        user_session="exec_abc",
    )

    payload = client._build_payload("hello", user_session="exec_abc")

    assert payload == {
        "model": "openclaw:main",
        "messages": [{"role": "user", "content": "hello"}],
        "user": "exec_abc",
    }


# 验证空字符串异常也能格式化出异常类型，避免测试链接失败原因为空。
def test_http_agent_client_formats_empty_exception_message():
    assert _format_exception_message(TimeoutError()) == "TimeoutError"
    assert _format_exception_message(ValueError("bad url")) == "ValueError: bad url"


def test_has_comparable_llm_output_requires_openai_output():
    assert not has_comparable_llm_output(
        [
            SimpleNamespace(span_type="llm", provider="litellm", output='{"assistantTexts":["ignored"]}'),
            SimpleNamespace(span_type="tool", provider=None, output="tool output"),
        ]
    )

    assert not has_comparable_llm_output(
        [
            SimpleNamespace(span_type="llm", provider="openai", output=""),
        ]
    )

    assert not has_comparable_llm_output(
        [
            SimpleNamespace(
                span_type="llm",
                provider="openai",
                output=(
                    '{"choices":[{"message":{"content":null,'
                    '"tool_calls":[{"function":{"name":"read","arguments":"{}"}}]}}]}'
                ),
            ),
        ]
    )

    assert has_comparable_llm_output(
        [
            SimpleNamespace(span_type="llm", provider="openai", output='{"choices":[{"message":{"content":"final"}}]}'),
        ]
    )


def test_trace_ready_for_comparison_requires_final_openai_output_not_min_count():
    spans = [
        SimpleNamespace(span_type="llm", provider="litellm", output='{"assistantTexts":["ignored"]}'),
        SimpleNamespace(
            span_type="llm",
            provider="openai",
            output=(
                '{"choices":[{"message":{"content":"planning",'
                '"tool_calls":[{"function":{"name":"exec","arguments":"{}"}}]}}]}'
            ),
        ),
        SimpleNamespace(span_type="tool", provider=None, output="tool output"),
    ]

    assert count_openai_llm_spans(spans) == 1
    assert not has_final_openai_llm_output(spans)
    assert not is_trace_ready_for_comparison(spans, expected_min_llm_count=2)
    assert is_trace_ready_for_comparison(
        [
            *spans,
            SimpleNamespace(span_type="llm", provider="openai", output='{"choices":[{"message":{"content":"final"}}]}'),
        ],
        expected_min_llm_count=2,
    )
    assert is_trace_ready_for_comparison(
        [
            SimpleNamespace(span_type="llm", provider="openai", output='{"choices":[{"message":{"content":"final"}}]}'),
        ],
        expected_min_llm_count=3,
    )

    unfinished_spans = [
        SimpleNamespace(span_type="llm", provider="openai", output='{"choices":[{"message":{"content":"previous text"}}]}'),
        SimpleNamespace(
            span_type="llm",
            provider="openai",
            output=(
                '{"choices":[{"message":{"content":null,'
                '"tool_calls":[{"function":{"name":"exec","arguments":"{}"}}]}}]}'
            ),
        ),
    ]
    assert not has_final_openai_llm_output(unfinished_spans)
    assert not is_trace_ready_for_comparison(unfinished_spans, expected_min_llm_count=1)


@pytest.mark.asyncio
async def test_create_execution_generates_execution_scoped_user_session(monkeypatch):
    created_executions = []

    class FakeAgentRepo:
        def __init__(self, session):
            del session

        async def get_by_id(self, agent_id):
            return SimpleNamespace(id=agent_id)

    class FakeScenarioRepo:
        def __init__(self, session):
            del session

        async def get_by_id(self, scenario_id):
            return SimpleNamespace(id=scenario_id)

    class FakeLLMService:
        def __init__(self, session):
            del session

        async def get_llm(self, llm_model_id):
            return SimpleNamespace(id=llm_model_id)

    class FakeExecutionRepo:
        def __init__(self, session):
            del session

        async def create(self, execution):
            created_executions.append(execution)
            return execution

    monkeypatch.setattr(execution_service_module, "SQLAlchemyAgentRepository", FakeAgentRepo)
    monkeypatch.setattr(execution_service_module, "SQLAlchemyScenarioRepository", FakeScenarioRepo)
    monkeypatch.setattr(execution_service_module, "LLMService", FakeLLMService)
    monkeypatch.setattr(execution_service_module, "SQLAlchemyExecutionRepository", FakeExecutionRepo)

    service = execution_service_module.ExecutionService(session=object())
    execution_id = await service.create_execution(
        CreateExecutionRequest(
            agent_id=uuid.uuid4(),
            scenario_id=uuid.uuid4(),
            llm_model_id=uuid.uuid4(),
        ),
        BackgroundTasks(),
    )

    assert len(created_executions) == 1
    execution = created_executions[0]
    assert execution.id == execution_id
    assert execution.user_session == f"exec_{execution_id.hex}"
