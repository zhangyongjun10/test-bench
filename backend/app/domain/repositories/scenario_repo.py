"""场景仓储"""

from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.entities.scenario import Scenario


class ScenarioRepository(ABC):
    @abstractmethod
    async def create(self, scenario: Scenario) -> Scenario:
        """创建新场景"""
        pass

    @abstractmethod
    async def update(self, scenario: Scenario) -> Scenario:
        """更新场景"""
        pass

    @abstractmethod
    async def delete(self, scenario_id: UUID) -> None:
        """软删除场景"""
        pass

    @abstractmethod
    async def get_by_id(self, scenario_id: UUID) -> Optional[Scenario]:
        """按 ID 获取"""
        pass

    @abstractmethod
    async def list_by_agent(self, agent_id: UUID, keyword: Optional[str] = None) -> List[Scenario]:
        """列出指定 Agent 的所有场景，支持搜索"""
        pass

    @abstractmethod
    async def list_all(self, keyword: Optional[str] = None, agent_id: Optional[UUID] = None) -> List[Scenario]:
        """列出所有场景，支持按关键词搜索和 Agent 筛选"""
        pass


class SQLAlchemyScenarioRepository(ScenarioRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, scenario: Scenario) -> Scenario:
        self.session.add(scenario)
        await self.session.commit()
        await self.session.refresh(scenario)
        return scenario

    async def update(self, scenario: Scenario) -> Scenario:
        self.session.add(scenario)
        await self.session.commit()
        await self.session.refresh(scenario)
        return scenario

    async def delete(self, scenario_id: UUID) -> None:
        scenario = await self.get_by_id(scenario_id)
        if scenario:
            scenario.deleted_at = datetime.utcnow()
            await self.session.commit()

    async def get_by_id(self, scenario_id: UUID) -> Optional[Scenario]:
        result = await self.session.execute(
            select(Scenario).where(Scenario.id == scenario_id, Scenario.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_by_agent(self, agent_id: UUID, keyword: Optional[str] = None) -> List[Scenario]:
        return await self.list_all(keyword, agent_id)

    async def list_all(self, keyword: Optional[str] = None, agent_id: Optional[UUID] = None) -> List[Scenario]:
        query = select(Scenario).where(Scenario.deleted_at.is_(None)).order_by(Scenario.created_at.desc())
        if agent_id is not None:
            query = query.where(Scenario.agent_id == agent_id)
        if keyword:
            query = query.where(Scenario.name.ilike(f"%{keyword}%"))
        result = await self.session.execute(query)
        return list(result.scalars().all())
