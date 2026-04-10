import uuid
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from app.clients.http_agent_client import HTTPAgentClient
from app.models.execution import CreateExecutionRequest
from app.services import execution_service as execution_service_module


def test_http_agent_client_builds_openclaw_payload_with_user():
    client = HTTPAgentClient(
        base_url="https://agent.example.com/chat",
        api_key="secret",
        user_session="exec_abc",
    )

    payload = client._build_payload("hello", "exec_abc")

    assert payload == {
        "model": "openclaw:main",
        "messages": [{"role": "user", "content": "hello"}],
        "user": "exec_abc",
    }


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
