"""Agent 仓储"""

from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.entities.agent import Agent


class AgentRepository(ABC):
    @abstractmethod
    async def create(self, agent: Agent) -> Agent:
        """创建新 Agent"""
        pass

    @abstractmethod
    async def update(self, agent: Agent) -> Agent:
        """更新 Agent"""
        pass

    @abstractmethod
    async def delete(self, agent_id: UUID) -> None:
        """软删除 Agent"""
        pass

    @abstractmethod
    async def get_by_id(self, agent_id: UUID) -> Optional[Agent]:
        """按 ID 获取"""
        pass

    @abstractmethod
    async def list_all(self, keyword: Optional[str] = None) -> List[Agent]:
        """列表，支持搜索"""
        pass


class SQLAlchemyAgentRepository(AgentRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, agent: Agent) -> Agent:
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def update(self, agent: Agent) -> Agent:
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def delete(self, agent_id: UUID) -> None:
        agent = await self.get_by_id(agent_id)
        if agent:
            from datetime import datetime
            agent.deleted_at = datetime.utcnow()
            await self.session.commit()

    async def get_by_id(self, agent_id: UUID) -> Optional[Agent]:
        result = await self.session.execute(
            select(Agent).where(Agent.id == agent_id, Agent.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_all(self, keyword: Optional[str] = None) -> List[Agent]:
        query = select(Agent).where(Agent.deleted_at.is_(None)).order_by(Agent.created_at.desc())
        if keyword:
            query = query.where(Agent.name.ilike(f"%{keyword}%"))
        result = await self.session.execute(query)
        return list(result.scalars().all())
