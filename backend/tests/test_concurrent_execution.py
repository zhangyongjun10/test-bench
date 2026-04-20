import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.config import settings
from app.domain.entities.execution import ExecutionStatus
from app.services.concurrent_execution_service import (
    ComparisonRunOutcome,
    ComparisonRunState,
    ConcurrentCallStatus,
    ConcurrentExecutionService,
)


# 验证并发执行调用 Agent 时固定使用 OpenClaw 主模型，避免把比对模型误传给 Agent。
@pytest.mark.asyncio
async def test_concurrent_execution_uses_openclaw_agent_model_for_agent_call():
    created_executions = []
    updated_executions = []

    # 伪造仓储对象，记录创建和更新的执行任务，避免测试依赖真实数据库。
    class FakeExecutionRepository:
        # 初始化伪仓储，保留 session 属性以兼容服务调用。
        def __init__(self):
            self.session = object()

        # 创建执行记录并补齐 ID，模拟 SQLAlchemy 仓储返回持久化实体。
        async def create(self, execution):
            created_executions.append(execution)
            return execution

        # 记录执行状态更新，供测试验证调用链路完成。
        async def update(self, execution):
            updated_executions.append(execution.status)
            return execution

    # 伪造 Agent 客户端，记录最终发送给 OpenClaw 的 model 和 user_session。
    class FakeAgentClient:
        # 初始化伪客户端调用记录。
        def __init__(self):
            self.called_model = None
            self.called_user_session = None

        # 模拟 Agent 调用成功，并记录请求模型。
        async def invoke(self, prompt, trace_id=None, model="openclaw:main", user_session=None):
            del prompt, trace_id
            self.called_model = model
            self.called_user_session = user_session
            return "ok", {}

    repo = FakeExecutionRepository()
    client = FakeAgentClient()
    service = ConcurrentExecutionService(session=object())
    agent = SimpleNamespace(id=uuid.uuid4())
    agent_config = SimpleNamespace(id=agent.id)
    batch_started_at = datetime.now(UTC)
    service._build_client = lambda _: client

    prepared_call = await service._prepare_single_call(
        batch_id="batch-12345678",
        input_text="查询深圳今天天气",
        scenario_id=uuid.uuid4(),
        llm_model_id=None,
        agent=agent,
        repo=repo,
        call_index=1,
    )
    prepared_call.execution.created_at = batch_started_at
    prepared_call.execution.started_at = batch_started_at
    result = await service._execute_single_call(
        input_text="查询深圳今天天气",
        llm_model_id=None,
        agent=agent_config,
        repo=repo,
        prepared_call=prepared_call,
    )

    assert result.status == "completed"
    assert client.called_model == "openclaw:main"
    assert len(created_executions) == 1
    assert created_executions[0].user_session == f"exec_{created_executions[0].id.hex}"
    assert created_executions[0].created_at == batch_started_at
    assert created_executions[0].started_at == batch_started_at
    assert client.called_user_session == created_executions[0].user_session
    assert "completed" in updated_executions


# 验证 Agent 客户端构建失败也会把已经创建的 execution 收口为 failed，避免外层异常被吞掉。
@pytest.mark.asyncio
async def test_concurrent_execution_marks_failed_when_client_build_fails():
    updated_executions = []

    # 伪造仓储对象，记录失败状态回写。
    class FakeExecutionRepository:
        # 初始化伪仓储，保留 session 属性以兼容服务调用。
        def __init__(self):
            self.session = object()

        # 记录执行状态更新，供测试验证异常收口。
        async def update(self, execution):
            updated_executions.append((execution.status, execution.error_message))
            return execution

    service = ConcurrentExecutionService(session=object())
    service._build_client = lambda _: (_ for _ in ()).throw(RuntimeError("decrypt failed"))
    execution = SimpleNamespace(
        id=uuid.uuid4(),
        trace_id=str(uuid.uuid4()),
        user_session="exec_test",
        scenario_id=uuid.uuid4(),
        status=ExecutionStatus.RUNNING,
        error_message=None,
        completed_at=None,
    )
    prepared_call = SimpleNamespace(execution=execution, call_index=1)

    result = await service._execute_single_call(
        input_text="查询深圳今天天气",
        llm_model_id=None,
        agent=SimpleNamespace(id=uuid.uuid4()),
        repo=FakeExecutionRepository(),
        prepared_call=prepared_call,
    )

    assert result.status == ConcurrentCallStatus.AGENT_FAILED
    assert updated_executions[-1][0] == ExecutionStatus.FAILED
    assert "decrypt failed" in updated_executions[-1][1]


# 验证 Trace 未就绪时主流程停留在 comparing，等待延迟比对收口，不会提前标记 completed。
@pytest.mark.asyncio
async def test_concurrent_execution_keeps_comparing_when_comparison_deferred():
    updated_statuses = []

    # 伪造仓储对象，记录状态流转。
    class FakeExecutionRepository:
        # 初始化伪仓储，保留 session 属性以兼容服务调用。
        def __init__(self):
            self.session = object()

        # 记录执行状态更新，供测试验证 deferred 状态不被覆盖。
        async def update(self, execution):
            updated_statuses.append(execution.status)
            return execution

    # 伪造 Agent 客户端，模拟 OpenClaw 已返回文本但 Trace 仍需等待。
    class FakeAgentClient:
        # 模拟 Agent 调用成功，不返回 run_id，避免触发 trace_id 反查。
        async def invoke(self, prompt, trace_id=None, model="openclaw:main", user_session=None):
            del prompt, trace_id, model, user_session
            return "ok", {}

    service = ConcurrentExecutionService(session=object())
    service._build_client = lambda _: FakeAgentClient()

    # 伪造比对流程返回 deferred，表示延迟比对任务已安排。
    async def fake_run_comparison(*args, **kwargs):
        del args, kwargs
        return ComparisonRunOutcome(ComparisonRunState.DEFERRED)

    service._run_comparison = fake_run_comparison
    execution = SimpleNamespace(
        id=uuid.uuid4(),
        trace_id=str(uuid.uuid4()),
        user_session="exec_test",
        scenario_id=uuid.uuid4(),
        status=ExecutionStatus.RUNNING,
        original_response=None,
        completed_at=None,
    )
    prepared_call = SimpleNamespace(execution=execution, call_index=1)

    result = await service._execute_single_call(
        input_text="查询深圳今天天气",
        llm_model_id=uuid.uuid4(),
        agent=SimpleNamespace(id=uuid.uuid4()),
        repo=FakeExecutionRepository(),
        prepared_call=prepared_call,
    )

    assert result.status == ConcurrentCallStatus.COMPARISON_DEFERRED
    assert execution.status == ExecutionStatus.COMPARING
    assert ExecutionStatus.COMPLETED not in updated_statuses


# 验证批次状态统计会把 queued/running/pulling_trace/comparing 全部归入 running 聚合状态。
@pytest.mark.asyncio
async def test_concurrent_batch_status_counts_all_non_terminal_as_running():
    batch_id = "batch-test"
    executions = [
        SimpleNamespace(status=ExecutionStatus.QUEUED, id=uuid.uuid4(), trace_id="t1", original_request=None, original_response=None, started_at=None, completed_at=None, error_message=None, user_session="u1"),
        SimpleNamespace(status=ExecutionStatus.PULLING_TRACE, id=uuid.uuid4(), trace_id="t2", original_request=None, original_response=None, started_at=None, completed_at=None, error_message=None, user_session="u2"),
        SimpleNamespace(status=ExecutionStatus.COMPARING, id=uuid.uuid4(), trace_id="t3", original_request=None, original_response=None, started_at=None, completed_at=None, error_message=None, user_session="u3"),
    ]

    # 伪造 execution 仓储，返回批次下的非终态执行记录。
    class FakeExecutionRepository:
        # 查询批次执行明细，供状态接口汇总。
        async def get_by_batch_id(self, current_batch_id):
            assert current_batch_id == batch_id
            return executions

    # 伪造批次仓储，返回请求并发数和准备计数。
    class FakeBatchRepository:
        # 查询批次记录，供状态接口补充批次级统计。
        async def get_by_id(self, current_batch_id):
            assert current_batch_id == batch_id
            return SimpleNamespace(
                requested_concurrency=3,
                prepared_count=3,
                started_count=3,
                prepare_failed_count=0,
                start_mark_failed_count=0,
                status="running",
                error_message=None,
                agent_started_at=None,
            )

    service = ConcurrentExecutionService(session=object())
    service.repo = FakeExecutionRepository()
    service.batch_repo = FakeBatchRepository()

    status = await service.get_concurrent_execution_status(batch_id)

    assert status["aggregate_status"] == "running"
    assert status["running"] == 3
    assert status["queued"] == 1
    assert status["pulling_trace"] == 1
    assert status["comparing"] == 1


# 验证超过系统最大并发数会被后端直接拒绝，不会创建批次或后台任务。
@pytest.mark.asyncio
async def test_concurrent_execution_rejects_concurrency_over_limit(monkeypatch):
    monkeypatch.setattr(settings, "concurrent_execution_max_concurrency", 2)
    service = ConcurrentExecutionService(session=object())

    # 伪造后台任务容器，确保超限时不会注册后台任务。
    class FakeBackgroundTasks:
        # 后台任务注册入口，超限测试不应该走到这里。
        def add_task(self, *args, **kwargs):
            raise AssertionError("should not add background task")

    with pytest.raises(ValueError, match="并发数超过系统上限"):
        await service.create_concurrent_execution(
            input_text="查询深圳今天天气",
            concurrency=3,
            background_tasks=FakeBackgroundTasks(),
            scenario_id=uuid.uuid4(),
            llm_model_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
        )
