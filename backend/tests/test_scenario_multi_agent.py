import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks
from pydantic import ValidationError

os.environ.setdefault("ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")

from app.models.execution import CreateExecutionRequest
from app.models.scenario import ScenarioCreate, ScenarioUpdate
from app.services.execution_service import ExecutionService
from app.services.scenario_service import ScenarioService


# 构造统一的时间字段，避免测试里重复声明时间对象并影响断言可读性。
def build_timestamp() -> datetime:
    return datetime.now(UTC)


# 伪造 Case 仓储，覆盖多 Agent 单记录模型下创建、更新和绑定替换的关键路径。
class FakeScenarioRepository:
    """在不依赖真实数据库的前提下，记录服务层对 Case 仓储的调用行为。"""

    def __init__(self):
        now = build_timestamp()
        self.scenario = SimpleNamespace(
            id=uuid4(),
            name="Old Case",
            description="old description",
            prompt="old prompt",
            baseline_result="old baseline",
            llm_count_min=0,
            llm_count_max=2,
            compare_enabled=True,
            created_at=now,
            updated_at=now,
        )
        self.create_count = 0
        self.deleted_ids: list[str] = []
        self.replace_calls: list[tuple[str, list[str]]] = []
        self.binding_map: dict = {}

    async def create(self, scenario):
        """模拟创建主记录时只落一条 Case，并回填统一的主键与时间字段。"""

        self.create_count += 1
        scenario.id = self.scenario.id
        scenario.created_at = self.scenario.created_at
        scenario.updated_at = self.scenario.updated_at
        self.scenario = scenario
        return scenario

    async def update(self, scenario):
        """模拟更新主记录，保留同一条 Case 主键不变。"""

        self.scenario = scenario
        return scenario

    async def delete(self, scenario_id):
        """记录被删除的 Case 主键，模拟服务层触发真实物理删除。"""

        self.deleted_ids.append(str(scenario_id))

    async def get_by_id(self, scenario_id):
        """返回唯一的伪造 Case，便于验证编辑仍作用于单条记录。"""

        return self.scenario if scenario_id == self.scenario.id else None

    async def list_by_agent(self, agent_id, keyword=None):
        """当前测试不覆盖按 Agent 列表查询，因此直接复用通用列表实现。"""

        del agent_id
        return await self.list_all(keyword=keyword)

    async def list_all(self, keyword=None, agent_id=None):
        """当前测试只需返回单条记录，过滤逻辑不在该伪仓储中展开。"""

        del keyword, agent_id
        return [self.scenario]

    async def replace_agents(self, scenario_id, agent_ids):
        """记录 Agent 绑定替换结果，用于断言服务层没有创建重复 Case。"""

        normalized_ids = [str(agent_id) for agent_id in agent_ids]
        self.replace_calls.append((str(scenario_id), normalized_ids))
        self.binding_map[scenario_id] = [(agent_id, f"Agent-{index}") for index, agent_id in enumerate(agent_ids, start=1)]

    async def get_agent_bindings(self, scenario_ids):
        """返回测试中预置的 Agent 绑定结果，模拟列表与详情页聚合读取。"""

        return {scenario_id: self.binding_map.get(scenario_id, []) for scenario_id in scenario_ids}

    async def is_bound_to_agent(self, scenario_id, agent_id):
        """根据 replace_agents 记录判断 Agent 与 Case 是否存在绑定关系。"""

        return any(bound_agent_id == agent_id for bound_agent_id, _ in self.binding_map.get(scenario_id, []))


# 创建请求必须显式提供至少一个 Agent，避免出现没有归属的悬挂 Case。
def test_scenario_create_requires_agent_ids():
    """校验创建请求缺少 Agent 或传空数组时会被模型层拦截。"""

    with pytest.raises(ValidationError):
        ScenarioCreate(
            name="Case A",
            prompt="prompt",
            baseline_result="baseline",
        )

    with pytest.raises(ValidationError):
        ScenarioCreate(
            agent_ids=[],
            name="Case A",
            prompt="prompt",
            baseline_result="baseline",
        )


# 服务层创建 Case 时应只创建一条主记录，再一次性写入多 Agent 绑定集合。
@pytest.mark.asyncio
async def test_create_scenario_creates_single_case_with_multiple_agents():
    """验证多 Agent 创建只会产生一条 Case，并把归属信息聚合到中间表。"""

    fake_repo = FakeScenarioRepository()
    service = ScenarioService(session=SimpleNamespace())
    service.repo = fake_repo

    async def fake_ensure_agents_exist(agent_ids):
        del agent_ids

    service._ensure_agents_exist = fake_ensure_agents_exist

    agent_ids = [uuid4(), uuid4(), uuid4()]
    response = await service.create_scenario(
        ScenarioCreate(
            agent_ids=agent_ids,
            name="Shared Case",
            description="shared",
            prompt="hello",
            baseline_result="world",
            llm_count_min=1,
            llm_count_max=3,
            compare_enabled=True,
        )
    )

    assert fake_repo.create_count == 1
    assert fake_repo.replace_calls == [(str(fake_repo.scenario.id), [str(agent_id) for agent_id in agent_ids])]
    assert response.id == fake_repo.scenario.id
    assert response.agent_ids == agent_ids
    assert response.agent_names == ["Agent-1", "Agent-2", "Agent-3"]


# 编辑 Case 时应整体替换 Agent 集合，而不是继续扩散成多条重复记录。
@pytest.mark.asyncio
async def test_update_scenario_replaces_agent_bindings():
    """验证编辑 Case 时仍然只更新同一条记录，并覆盖 Agent 归属集合。"""

    fake_repo = FakeScenarioRepository()
    service = ScenarioService(session=SimpleNamespace())
    service.repo = fake_repo

    async def fake_ensure_agents_exist(agent_ids):
        del agent_ids

    service._ensure_agents_exist = fake_ensure_agents_exist

    new_agent_ids = [uuid4(), uuid4()]
    response = await service.update_scenario(
        fake_repo.scenario.id,
        ScenarioUpdate(
            agent_ids=new_agent_ids,
            name="Updated Case",
            prompt="updated prompt",
            baseline_result="updated baseline",
            llm_count_min=2,
            llm_count_max=4,
            compare_enabled=False,
        ),
    )

    assert response is not None
    assert fake_repo.scenario.name == "Updated Case"
    assert fake_repo.scenario.prompt == "updated prompt"
    assert fake_repo.replace_calls == [(str(fake_repo.scenario.id), [str(agent_id) for agent_id in new_agent_ids])]
    assert response.agent_ids == new_agent_ids
    assert response.agent_names == ["Agent-1", "Agent-2"]


# 删除 Case 时应直接触发仓储层物理删除，而不是只做软删标记。
@pytest.mark.asyncio
async def test_delete_scenario_physically_deletes_case():
    """验证删除 Case 会调用仓储层物理删除，并返回成功结果。"""

    fake_repo = FakeScenarioRepository()
    service = ScenarioService(session=SimpleNamespace())
    service.repo = fake_repo

    success = await service.delete_scenario(fake_repo.scenario.id)

    assert success is True
    assert fake_repo.deleted_ids == [str(fake_repo.scenario.id)]


# 若 Case 仍被执行、比对或回放引用，删除动作必须明确失败而不是表面删除成功。
@pytest.mark.asyncio
async def test_delete_scenario_rejects_referenced_case():
    """验证仓储层发现外键引用后，服务层会把错误继续抛出给接口处理。"""

    fake_repo = FakeScenarioRepository()
    service = ScenarioService(session=SimpleNamespace())
    service.repo = fake_repo

    async def fake_delete(scenario_id):
        del scenario_id
        raise ValueError("当前 Case 已被执行记录、比对记录或回放任务引用，无法删除")

    fake_repo.delete = fake_delete

    with pytest.raises(ValueError, match="当前 Case 已被执行记录、比对记录或回放任务引用，无法删除"):
        await service.delete_scenario(fake_repo.scenario.id)


# 执行创建必须校验 Agent 与 Case 的绑定关系，避免执行页提交非法组合后进入后台任务。
@pytest.mark.asyncio
async def test_create_execution_rejects_unbound_scenario(monkeypatch):
    """验证当 Case 不属于当前 Agent 时，执行链路会在任务创建前直接拒绝。"""

    service = ExecutionService(session=SimpleNamespace())

    async def fake_get_agent(agent_id):
        return SimpleNamespace(id=agent_id)

    async def fake_get_scenario(scenario_id):
        return SimpleNamespace(id=scenario_id, prompt="prompt")

    async def fake_is_bound_to_agent(scenario_id, agent_id):
        del scenario_id, agent_id
        return False

    service.agent_repo = SimpleNamespace(get_by_id=fake_get_agent)
    service.scenario_repo = SimpleNamespace(
        get_by_id=fake_get_scenario,
        is_bound_to_agent=fake_is_bound_to_agent,
    )

    class FakeLlmService:
        """伪造比对模型查询，避免该测试依赖真实数据库。"""

        def __init__(self, session):
            del session

        async def get_llm(self, llm_model_id):
            return SimpleNamespace(id=llm_model_id)

    monkeypatch.setattr("app.services.execution_service.LLMService", FakeLlmService)

    with pytest.raises(ValueError, match="is not bound to agent"):
        await service.create_execution(
            CreateExecutionRequest(
                agent_id=uuid4(),
                scenario_id=uuid4(),
                llm_model_id=uuid4(),
            ),
            BackgroundTasks(),
        )
