"""Execution repository interfaces and SQLAlchemy implementation."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.comparison import ComparisonResult
from app.domain.entities.execution import ExecutionJob, ExecutionRunSource


class ExecutionRepository(ABC):
    @abstractmethod
    async def create(self, execution: ExecutionJob) -> ExecutionJob:
        """Create an execution job."""

    @abstractmethod
    async def update(self, execution: ExecutionJob) -> ExecutionJob:
        """Update an execution job."""

    @abstractmethod
    async def delete(self, execution_id: UUID) -> None:
        """Delete a single execution job."""

    @abstractmethod
    async def get_by_id(self, execution_id: UUID) -> Optional[ExecutionJob]:
        """Fetch an execution by id."""

    @abstractmethod
    async def list_all(
        self,
        agent_id: Optional[UUID] = None,
        scenario_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[int, List[ExecutionJob]]:
        """List executions with total count."""

    @abstractmethod
    async def count_old_data(self, days: int = 30) -> int:
        """Count executions older than the retention threshold."""

    @abstractmethod
    async def delete_old_data(self, days: int = 30) -> int:
        """Delete executions older than the retention threshold."""


class SQLAlchemyExecutionRepository(ExecutionRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _delete_comparisons_for_execution(self, execution_id: UUID) -> int:
        stmt = delete(ComparisonResult).where(ComparisonResult.execution_id == execution_id)
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def _delete_comparisons_for_old_executions(self, cutoff: datetime) -> int:
        old_execution_ids = (
            select(ExecutionJob.id)
            .where(ExecutionJob.created_at < cutoff)
            .scalar_subquery()
        )
        stmt = delete(ComparisonResult).where(ComparisonResult.execution_id.in_(old_execution_ids))
        result = await self.session.execute(stmt)
        return result.rowcount or 0

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
            await self._delete_comparisons_for_execution(execution_id)
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
        offset: int = 0,
    ) -> tuple[int, List[ExecutionJob]]:
        from sqlalchemy import func

        count_query = select(func.count()).select_from(ExecutionJob)
        data_query = select(ExecutionJob).order_by(desc(ExecutionJob.created_at))

        count_query = count_query.where(
            ExecutionJob.agent_id.isnot(None),
            ExecutionJob.scenario_id.isnot(None),
            ExecutionJob.run_source == ExecutionRunSource.NORMAL,
        )
        data_query = data_query.where(
            ExecutionJob.agent_id.isnot(None),
            ExecutionJob.scenario_id.isnot(None),
            ExecutionJob.run_source == ExecutionRunSource.NORMAL,
        )

        if agent_id:
            count_query = count_query.where(ExecutionJob.agent_id == agent_id)
            data_query = data_query.where(ExecutionJob.agent_id == agent_id)
        if scenario_id:
            count_query = count_query.where(ExecutionJob.scenario_id == scenario_id)
            data_query = data_query.where(ExecutionJob.scenario_id == scenario_id)

        count_result = await self.session.execute(count_query)
        total = count_result.scalar_one()

        data_query = data_query.limit(limit).offset(offset)
        data_result = await self.session.execute(data_query)
        items = list(data_result.scalars().all())

        return total, items

    async def count_old_data(self, days: int = 30) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await self.session.execute(
            select(ExecutionJob).where(ExecutionJob.created_at < cutoff)
        )
        return len(list(result.scalars().all()))

    async def delete_old_data(self, days: int = 30) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        await self._delete_comparisons_for_old_executions(cutoff)
        stmt = delete(ExecutionJob).where(ExecutionJob.created_at < cutoff)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount or 0
