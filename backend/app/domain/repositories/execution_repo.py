"""执行任务仓储"""

from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy import select, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.entities.execution import ExecutionJob


class ExecutionRepository(ABC):
    @abstractmethod
    async def create(self, execution: ExecutionJob) -> ExecutionJob:
        """创建执行任务"""
        pass

    @abstractmethod
    async def update(self, execution: ExecutionJob) -> ExecutionJob:
        """更新执行任务"""
        pass

    @abstractmethod
    async def delete(self, execution_id: UUID) -> None:
        """删除执行任务"""
        pass

    @abstractmethod
    async def get_by_id(self, execution_id: UUID) -> Optional[ExecutionJob]:
        """按 ID 获取"""
        pass

    @abstractmethod
    async def list_all(
        self,
        agent_id: Optional[UUID] = None,
        scenario_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[int, List[ExecutionJob]]:
        """列表查询，返回 (total_count, items)"""
        pass

    @abstractmethod
    async def count_old_data(self, days: int = 30) -> int:
        """统计超过天数的旧数据数量"""
        pass

    @abstractmethod
    async def delete_old_data(self, days: int = 30) -> int:
        """删除超过天数的旧数据"""
        pass


class SQLAlchemyExecutionRepository(ExecutionRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, execution: ExecutionJob) -> ExecutionJob:
        self.session.add(execution)
        await self.session.commit()
        await self.session.refresh(execution)
        return execution

    async def update(self, execution: ExecutionJob) -> ExecutionJob:
        self.session.add(execution)
        await self.session.commit()
        await self.session.refresh(execution)
        return execution

    async def delete(self, execution_id: UUID) -> None:
        execution = await self.get_by_id(execution_id)
        if execution:
            await self.session.delete(execution)
            await self.session.commit()

    async def get_by_id(self, execution_id: UUID) -> Optional[ExecutionJob]:
        result = await self.session.execute(
            select(ExecutionJob).where(ExecutionJob.id == execution_id)
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        agent_id: Optional[UUID] = None,
        scenario_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[int, List[ExecutionJob]]:
        from sqlalchemy import func

        # 构建条件查询
        count_query = select(func.count()).select_from(ExecutionJob)
        data_query = select(ExecutionJob).order_by(desc(ExecutionJob.created_at))

        # 过滤掉外键为 NULL 的脏记录（DB 约束未生效时遗留的无效数据）
        count_query = count_query.where(
            ExecutionJob.agent_id.isnot(None),
            ExecutionJob.scenario_id.isnot(None)
        )
        data_query = data_query.where(
            ExecutionJob.agent_id.isnot(None),
            ExecutionJob.scenario_id.isnot(None)
        )

        if agent_id:
            count_query = count_query.where(ExecutionJob.agent_id == agent_id)
            data_query = data_query.where(ExecutionJob.agent_id == agent_id)
        if scenario_id:
            count_query = count_query.where(ExecutionJob.scenario_id == scenario_id)
            data_query = data_query.where(ExecutionJob.scenario_id == scenario_id)

        # 获取总数
        count_result = await self.session.execute(count_query)
        total = count_result.scalar_one()

        # 获取分页数据
        data_query = data_query.limit(limit).offset(offset)
        data_result = await self.session.execute(data_query)
        items = list(data_result.scalars().all())

        return (total, items)

    async def count_old_data(self, days: int = 30) -> int:
        cutoff = datetime.utcnow() - timedelta(days=days)
        result = await self.session.execute(
            select(ExecutionJob).where(ExecutionJob.created_at < cutoff)
        )
        return len(list(result.scalars().all()))

    async def delete_old_data(self, days: int = 30) -> int:
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = delete(ExecutionJob).where(ExecutionJob.created_at < cutoff)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount
