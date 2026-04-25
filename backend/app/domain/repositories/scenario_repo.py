"""场景仓储接口与 SQLAlchemy 实现。"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.agent import Agent
from app.domain.entities.scenario import Scenario, ScenarioAgent


class ScenarioRepository(ABC):
    """定义 Case 持久化所需的基础读写与 Agent 绑定能力。"""

    @abstractmethod
    async def create(self, scenario: Scenario) -> Scenario:
        """创建单条 Case 主记录，并返回带主键的实体。"""

    @abstractmethod
    async def update(self, scenario: Scenario) -> Scenario:
        """更新单条 Case 主记录，保留既有主键与时间戳语义。"""

    @abstractmethod
    async def delete(self, scenario_id: UUID) -> None:
        """软删除 Case，避免影响历史执行与回放记录的可追溯性。"""

    @abstractmethod
    async def get_by_id(self, scenario_id: UUID) -> Optional[Scenario]:
        """按 Case 主键查询未删除记录，不返回已软删数据。"""

    @abstractmethod
    async def list_by_agent(self, agent_id: UUID, keyword: Optional[str] = None) -> list[Scenario]:
        """查询关联指定 Agent 的 Case，并支持按名称关键字过滤。"""

    @abstractmethod
    async def list_all(self, keyword: Optional[str] = None, agent_id: Optional[UUID] = None) -> list[Scenario]:
        """查询 Case 列表；传入 Agent 时只返回已建立关联的记录。"""

    @abstractmethod
    async def replace_agents(self, scenario_id: UUID, agent_ids: list[UUID]) -> None:
        """整体替换 Case 的 Agent 关联集合，避免前端多选回写产生残留绑定。"""

    @abstractmethod
    async def get_agent_bindings(self, scenario_ids: list[UUID]) -> dict[UUID, list[tuple[UUID, str]]]:
        """批量读取 Case 对应的 Agent 主键与名称，供列表和详情统一组装响应。"""

    @abstractmethod
    async def is_bound_to_agent(self, scenario_id: UUID, agent_id: UUID) -> bool:
        """校验 Case 是否已关联指定 Agent，用于执行创建前的安全拦截。"""


class SQLAlchemyScenarioRepository(ScenarioRepository):
    """基于 SQLAlchemy 的 Case 仓储实现，负责 join table 的真实读写。"""

    def __init__(self, session: AsyncSession):
        """保存异步会话，供仓储方法在同一事务上下文中复用。"""

        self.session = session

    async def create(self, scenario: Scenario) -> Scenario:
        """创建 Case 主记录并提交，使后续 Agent 绑定可以直接使用生成后的主键。"""

        self.session.add(scenario)
        await self.session.commit()
        await self.session.refresh(scenario)
        return scenario

    async def update(self, scenario: Scenario) -> Scenario:
        """更新 Case 主记录并刷新实体，确保响应里拿到最新更新时间。"""

        self.session.add(scenario)
        await self.session.commit()
        await self.session.refresh(scenario)
        return scenario

    async def delete(self, scenario_id: UUID) -> None:
        """将 Case 标记为软删除，避免破坏历史执行与比对数据的引用链路。"""

        scenario = await self.get_by_id(scenario_id)
        if scenario:
            scenario.deleted_at = datetime.now(UTC)
            await self.session.commit()

    async def get_by_id(self, scenario_id: UUID) -> Optional[Scenario]:
        """按主键读取未删除 Case，详情页和编辑页都依赖该统一入口。"""

        result = await self.session.execute(
            select(Scenario).where(Scenario.id == scenario_id, Scenario.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_by_agent(self, agent_id: UUID, keyword: Optional[str] = None) -> list[Scenario]:
        """复用通用列表查询，只保留与目标 Agent 有关联的 Case。"""

        return await self.list_all(keyword=keyword, agent_id=agent_id)

    async def list_all(self, keyword: Optional[str] = None, agent_id: Optional[UUID] = None) -> list[Scenario]:
        """查询 Case 列表；筛选 Agent 时通过中间表去重，保证同一 Case 只返回一条。"""

        query = select(Scenario).where(Scenario.deleted_at.is_(None))
        if agent_id is not None:
            query = query.join(ScenarioAgent, ScenarioAgent.scenario_id == Scenario.id).where(
                ScenarioAgent.agent_id == agent_id
            )
        if keyword:
            query = query.where(Scenario.name.ilike(f"%{keyword}%"))
        result = await self.session.execute(query.order_by(Scenario.created_at.desc()).distinct())
        return list(result.scalars().all())

    async def replace_agents(self, scenario_id: UUID, agent_ids: list[UUID]) -> None:
        """整体覆盖 Agent 绑定集合，保证编辑保存后的归属集合与表单完全一致。"""

        unique_agent_ids = list(dict.fromkeys(agent_ids))
        await self.session.execute(delete(ScenarioAgent).where(ScenarioAgent.scenario_id == scenario_id))
        self.session.add_all(
            [ScenarioAgent(scenario_id=scenario_id, agent_id=agent_id) for agent_id in unique_agent_ids]
        )
        await self.session.commit()

    async def get_agent_bindings(self, scenario_ids: list[UUID]) -> dict[UUID, list[tuple[UUID, str]]]:
        """批量读取 Agent 绑定，统一过滤已删除 Agent，避免页面展示脏数据。"""

        if not scenario_ids:
            return {}

        result = await self.session.execute(
            select(ScenarioAgent.scenario_id, Agent.id, Agent.name)
            .join(Agent, Agent.id == ScenarioAgent.agent_id)
            .where(ScenarioAgent.scenario_id.in_(scenario_ids), Agent.deleted_at.is_(None))
            .order_by(Agent.name.asc())
        )
        bindings: dict[UUID, list[tuple[UUID, str]]] = {}
        for scenario_id, agent_id, agent_name in result.all():
            bindings.setdefault(scenario_id, []).append((agent_id, agent_name))
        return bindings

    async def is_bound_to_agent(self, scenario_id: UUID, agent_id: UUID) -> bool:
        """校验执行时的 Agent 与 Case 关系，阻止未授权组合进入执行链路。"""

        result = await self.session.execute(
            select(ScenarioAgent.scenario_id).where(
                ScenarioAgent.scenario_id == scenario_id,
                ScenarioAgent.agent_id == agent_id,
            )
        )
        return result.scalar_one_or_none() is not None
