import uuid
from types import SimpleNamespace

import pytest

from app.services.concurrent_execution_service import ConcurrentExecutionService


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
    agent = SimpleNamespace(id=uuid.uuid4(), user_session=None)

    result = await service._execute_single_call(
        batch_id="batch-12345678",
        input_text="查询深圳今天天气",
        scenario_id=uuid.uuid4(),
        llm_model_id=None,
        agent=agent,
        client=client,
        repo=repo,
        call_index=1,
    )

    assert result["success"] is True
    assert client.called_model == "openclaw:main"
    assert len(created_executions) == 1
    assert created_executions[0].user_session == f"exec_{created_executions[0].id.hex}"
    assert client.called_user_session == created_executions[0].user_session
    assert "completed" in updated_executions
