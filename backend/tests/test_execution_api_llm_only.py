from datetime import UTC, datetime
import json
from types import SimpleNamespace
import uuid

import pytest
from fastapi import BackgroundTasks
from pydantic import ValidationError

from app.api import execution as execution_api
from app.api import scenario as scenario_api
from app.domain.entities.execution import ExecutionStatus
from app.domain.repositories import execution_repo as execution_repo_module
from app.domain.repositories import comparison_repo as comparison_repo_module
from app.domain.repositories import scenario_repo as scenario_repo_module
from app.models.execution import CreateExecutionRequest
from app.services import comparison as comparison_service_module
from app.services import execution_service as execution_service_module
from app.services import llm_service as llm_service_module
from app.services import trace_fetcher as trace_fetcher_module


def make_comparison(details: dict) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        scenario_id=uuid.uuid4(),
        llm_model_id=uuid.uuid4(),
        trace_id="trace-1",
        process_score=None,
        result_score=None,
        overall_passed=details.get("llm_count_check", {}).get("passed", False),
        details_json=json.dumps(details, ensure_ascii=False),
        status="completed",
        error_message=None,
        retry_count=0,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )


def test_create_execution_request_requires_llm_model_id():
    with pytest.raises(ValidationError):
        CreateExecutionRequest(
            agent_id=uuid.uuid4(),
            scenario_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_get_comparison_returns_llm_only_fields(monkeypatch):
    details = {
        "tool_comparisons": [],
        "llm_comparison": None,
        "llm_count_check": {
            "expected_min": 1,
            "expected_max": 2,
            "actual_count": 1,
            "passed": True,
        },
        "final_output_comparison": {
            "baseline_output": "baseline",
            "actual_output": "actual",
            "consistent": True,
            "reason": "same meaning",
        },
    }

    class FakeComparisonRepo:
        async def get_by_execution_id(self, session, execution_id):
            del session, execution_id
            return make_comparison(details)

    monkeypatch.setattr(execution_api, "SQLAlchemyComparisonRepository", lambda: FakeComparisonRepo())

    response = await execution_api.get_comparison(uuid.uuid4(), session=object())

    assert response.code == 0
    assert response.data.tool_comparisons == []
    assert response.data.llm_count_check is not None
    assert response.data.llm_count_check.expected_min == 1
    assert response.data.llm_count_check.passed is True
    assert response.data.final_output_comparison is not None
    assert response.data.final_output_comparison.consistent is True
    assert response.data.final_output_comparison.reason == "same meaning"
    assert response.data.llm_model_id is not None


@pytest.mark.asyncio
async def test_list_comparisons_returns_newest_results_with_model_id(monkeypatch):
    details = {
        "tool_comparisons": [],
        "llm_comparison": None,
        "llm_count_check": {
            "expected_min": 1,
            "expected_max": 2,
            "actual_count": 1,
            "passed": True,
        },
        "final_output_comparison": {
            "baseline_output": "baseline",
            "actual_output": "actual",
            "consistent": True,
            "reason": "same meaning",
        },
    }
    comparisons = [make_comparison(details), make_comparison(details)]

    class FakeComparisonRepo:
        async def list_by_execution_id(self, session, execution_id):
            del session, execution_id
            return comparisons

    monkeypatch.setattr(execution_api, "SQLAlchemyComparisonRepository", lambda: FakeComparisonRepo())

    response = await execution_api.list_comparisons(uuid.uuid4(), session=object())

    assert response.code == 0
    assert len(response.data) == 2
    assert response.data[0].id == comparisons[0].id
    assert response.data[0].llm_model_id == comparisons[0].llm_model_id


@pytest.mark.asyncio
async def test_get_comparison_maps_legacy_llm_comparison(monkeypatch):
    details = {
        "tool_comparisons": [],
        "llm_comparison": {
            "baseline_output": "legacy baseline",
            "actual_output": "legacy actual",
            "similarity": 0.9,
            "score": 1.0,
            "consistent": True,
            "reason": "legacy path",
        },
    }

    class FakeComparisonRepo:
        async def get_by_execution_id(self, session, execution_id):
            del session, execution_id
            return make_comparison(details)

    monkeypatch.setattr(execution_api, "SQLAlchemyComparisonRepository", lambda: FakeComparisonRepo())

    response = await execution_api.get_comparison(uuid.uuid4(), session=object())

    assert response.code == 0
    assert response.data.llm_comparison is not None
    assert response.data.final_output_comparison is not None
    assert response.data.final_output_comparison.baseline_output == "legacy baseline"
    assert response.data.final_output_comparison.actual_output == "legacy actual"
    assert response.data.final_output_comparison.consistent is True


@pytest.mark.asyncio
async def test_get_trace_returns_provider_for_llm_spans(monkeypatch):
    execution = SimpleNamespace(id=uuid.uuid4(), trace_id="trace-1")
    spans = [
        SimpleNamespace(
            span_id="llm-1",
            span_type="llm",
            name="gpt-4o",
            provider="openai",
            input="input",
            output="output",
            duration_ms=123,
            metrics=SimpleNamespace(ttft_ms=10.0, tpot_ms=2.5, input_tokens=9546, output_tokens=5),
        ),
        SimpleNamespace(
            span_id="tool-1",
            span_type="tool",
            name="read",
            provider=None,
            input="input",
            output="output",
            duration_ms=12,
            metrics=SimpleNamespace(ttft_ms=None, tpot_ms=None, input_tokens=0, output_tokens=0),
        ),
    ]

    class FakeExecutionService:
        def __init__(self, session):
            del session

        async def get_execution(self, execution_id):
            del execution_id
            return execution

    class FakeTraceFetcher:
        def __init__(self, session):
            del session

        async def fetch_spans(self, trace_id):
            del trace_id
            return spans

    monkeypatch.setattr(execution_api, "ExecutionService", FakeExecutionService)
    monkeypatch.setattr(execution_api, "TraceFetcherImpl", FakeTraceFetcher)

    response = await execution_api.get_trace(uuid.uuid4(), session=object())

    assert response.code == 0
    assert response.data.spans[0].provider == "openai"
    assert response.data.spans[0].input_tokens == 9546
    assert response.data.spans[0].output_tokens == 5
    assert response.data.spans[1].provider is None


@pytest.mark.asyncio
async def test_trigger_recompare_returns_404_when_llm_model_missing(monkeypatch):
    execution = SimpleNamespace(id=uuid.uuid4())

    class FakeExecutionRepo:
        def __init__(self, session):
            del session

        async def get_by_id(self, execution_id):
            del execution_id
            return execution

    class FakeLLMService:
        def __init__(self, session):
            del session

        async def get_llm(self, model_id):
            del model_id
            return None

    monkeypatch.setattr(execution_repo_module, "SQLAlchemyExecutionRepository", FakeExecutionRepo)
    monkeypatch.setattr(execution_api, "LLMService", FakeLLMService)

    response = await execution_api.trigger_recompare(
        execution_id=uuid.uuid4(),
        background_tasks=BackgroundTasks(),
        llm_model_id=uuid.uuid4(),
        session=object(),
    )

    assert response.code == 404
    assert response.message == "LLM model not found"


@pytest.mark.asyncio
async def test_trigger_recompare_enqueues_background_task(monkeypatch):
    execution = SimpleNamespace(id=uuid.uuid4())
    llm_model = SimpleNamespace(id=uuid.uuid4(), name="compare-model")
    background_tasks = BackgroundTasks()

    class FakeExecutionRepo:
        def __init__(self, session):
            del session

        async def get_by_id(self, execution_id):
            del execution_id
            return execution

    class FakeLLMService:
        def __init__(self, session):
            del session

        async def get_llm(self, model_id):
            del model_id
            return llm_model

    monkeypatch.setattr(execution_repo_module, "SQLAlchemyExecutionRepository", FakeExecutionRepo)
    monkeypatch.setattr(execution_api, "LLMService", FakeLLMService)

    execution_id = uuid.uuid4()
    llm_model_id = uuid.uuid4()
    response = await execution_api.trigger_recompare(
        execution_id=execution_id,
        background_tasks=background_tasks,
        llm_model_id=llm_model_id,
        session=object(),
    )

    assert response.code == 0
    assert response.data.success is True
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is execution_api.run_recompare
    assert task.args == (execution_id, llm_model_id)


@pytest.mark.asyncio
async def test_set_baseline_updates_only_baseline_result(monkeypatch):
    execution = SimpleNamespace(
        id=uuid.uuid4(),
        trace_id="trace-1",
        original_response='{"assistantTexts":["final answer"]}',
    )
    scenario = SimpleNamespace(
        id=uuid.uuid4(),
        baseline_result="old baseline",
        baseline_tool_calls='[{"name":"tool"}]',
    )

    class FakeExecutionRepo:
        def __init__(self, session):
            del session

        async def get_by_id(self, execution_id):
            del execution_id
            return execution

    class FakeScenarioRepo:
        def __init__(self, session):
            del session
            self.updated = None

        async def get_by_id(self, scenario_id):
            del scenario_id
            return scenario

        async def update(self, updated_scenario):
            self.updated = updated_scenario
            return updated_scenario

    class FakeTraceFetcher:
        def __init__(self, session):
            del session

        async def fetch_spans(self, trace_id):
            del trace_id
            return []

    monkeypatch.setattr(execution_repo_module, "SQLAlchemyExecutionRepository", FakeExecutionRepo)
    monkeypatch.setattr(scenario_repo_module, "SQLAlchemyScenarioRepository", FakeScenarioRepo)
    monkeypatch.setattr(trace_fetcher_module, "TraceFetcherImpl", FakeTraceFetcher)

    response = await scenario_api.set_baseline_from_execution(
        scenario_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        session=object(),
    )

    assert response.code == 0
    assert scenario.baseline_result == "final answer"
    assert scenario.baseline_tool_calls == '[{"name":"tool"}]'


@pytest.mark.asyncio
async def test_run_recompare_with_session_updates_comparison_and_execution(monkeypatch):
    execution = SimpleNamespace(
        id=uuid.uuid4(),
        scenario_id=uuid.uuid4(),
        trace_id="trace-1",
        status="completed",
        comparison_score=12.0,
        comparison_passed=None,
        error_message="old execution error",
    )
    scenario = SimpleNamespace(
        id=execution.scenario_id,
        baseline_result="baseline",
        llm_count_min=1,
        llm_count_max=2,
    )
    llm_model = SimpleNamespace(id=uuid.uuid4(), comparison_prompt="prompt")
    created_comparisons: list[object] = []
    updated_executions: list[object] = []

    class FakeSession:
        def __init__(self):
            self.commits = 0

        async def commit(self):
            self.commits += 1

    class FakeExecutionRepo:
        def __init__(self, session):
            del session

        async def get_by_id(self, execution_id):
            del execution_id
            return execution

        async def update(self, updated_execution):
            updated_executions.append(updated_execution)
            return updated_execution

    class FakeScenarioRepo:
        def __init__(self, session):
            del session

        async def get_by_id(self, scenario_id):
            del scenario_id
            return scenario

    class FakeComparisonRepo:
        async def create(self, session, comparison):
            del session
            created_comparisons.append(comparison)
            return comparison

    class FakeTraceFetcher:
        def __init__(self, session):
            del session

        async def fetch_spans(self, trace_id):
            del trace_id
            return [
                SimpleNamespace(
                    span_type="llm",
                    provider="openai",
                    output='{"assistantTexts":["actual"]}',
                )
            ]

    class FakeLLMService:
        def __init__(self, session):
            del session

        async def get_llm(self, model_id):
            del model_id
            return llm_model

        def get_client(self, model):
            return f"client-for-{model.id}"

    class FakeComparisonService:
        def __init__(self, llm_client, comparison_repo):
            assert llm_client == f"client-for-{llm_model.id}"
            assert isinstance(comparison_repo, FakeComparisonRepo)

        async def detailed_compare(self, scenario, execution, trace_spans, llm_model):
            del scenario, execution, trace_spans
            return SimpleNamespace(
                process_score=None,
                result_score=None,
                overall_passed=True,
                llm_model_id=llm_model.id,
                details_json='{"llm_count_check":{"passed":true},"final_output_comparison":{"consistent":true}}',
                status="completed",
                error_message=None,
            )

    monkeypatch.setattr(execution_api, "SQLAlchemyExecutionRepository", FakeExecutionRepo)
    monkeypatch.setattr(scenario_repo_module, "SQLAlchemyScenarioRepository", FakeScenarioRepo)
    monkeypatch.setattr(comparison_repo_module, "SQLAlchemyComparisonRepository", lambda: FakeComparisonRepo())
    monkeypatch.setattr(trace_fetcher_module, "TraceFetcherImpl", FakeTraceFetcher)
    monkeypatch.setattr(llm_service_module, "LLMService", FakeLLMService)
    monkeypatch.setattr(comparison_service_module, "ComparisonService", FakeComparisonService)

    session = FakeSession()
    await execution_api._run_recompare_with_session(
        session=session,
        execution_id=execution.id,
        llm_model_id=llm_model.id,
    )

    assert len(created_comparisons) == 1
    comparison = created_comparisons[0]
    assert comparison.overall_passed is True
    assert comparison.status == "completed"
    assert execution.status == ExecutionStatus.COMPLETED
    assert execution.comparison_score is None
    assert execution.comparison_passed is True
    assert execution.error_message is None
    assert updated_executions[-1] is execution
    assert session.commits >= 2


@pytest.mark.asyncio
async def test_delete_execution_removes_comparisons_before_execution(monkeypatch):
    execution_id = uuid.uuid4()
    execution = SimpleNamespace(id=execution_id)
    deleted_execution_ids: list[uuid.UUID] = []
    deleted_comparison_ids: list[uuid.UUID] = []

    class FakeExecutionRepo:
        def __init__(self, session):
            del session

        async def get_by_id(self, target_execution_id):
            assert target_execution_id == execution_id
            return execution

        async def delete(self, target_execution_id):
            deleted_execution_ids.append(target_execution_id)

    class FakeComparisonRepo:
        async def delete_by_execution_id(self, session, target_execution_id):
            del session
            deleted_comparison_ids.append(target_execution_id)
            return 2

    monkeypatch.setattr(execution_service_module, "SQLAlchemyExecutionRepository", FakeExecutionRepo)
    monkeypatch.setattr(execution_service_module, "SQLAlchemyComparisonRepository", lambda: FakeComparisonRepo())

    service = execution_service_module.ExecutionService(session=object())
    result = await service.delete_execution(execution_id)

    assert result is True
    assert deleted_comparison_ids == [execution_id]
    assert deleted_execution_ids == [execution_id]


@pytest.mark.asyncio
async def test_execution_repo_delete_old_data_removes_comparisons_first():
    statements: list[object] = []

    class FakeResult:
        def __init__(self, rowcount=0):
            self.rowcount = rowcount

        def scalars(self):
            return self

        def all(self):
            return []

    class FakeSession:
        def __init__(self):
            self.commit_count = 0

        async def execute(self, stmt):
            statements.append(stmt)
            return FakeResult(rowcount=3)

        async def commit(self):
            self.commit_count += 1

    repo = execution_repo_module.SQLAlchemyExecutionRepository(FakeSession())
    deleted = await repo.delete_old_data(days=30)

    assert deleted == 3
    assert len(statements) == 2
    assert "DELETE FROM comparison_results" in str(statements[0])
    assert "DELETE FROM execution_jobs" in str(statements[1])
    assert repo.session.commit_count == 1
