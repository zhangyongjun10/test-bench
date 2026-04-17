"""Execution repository interfaces and SQLAlchemy implementation."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.comparison import ComparisonResult
from app.domain.entities.execution import ExecutionJob, ExecutionRunSource
from app.domain.entities.replay import ReplayTask


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

    @abstractmethod
    async def get_by_batch_id(self, batch_id: str) -> List[ExecutionJob]:
        """List executions for a batch id."""


class SQLAlchemyExecutionRepository(ExecutionRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _delete_comparisons_for_execution(self, execution_id: UUID) -> int:
        stmt = delete(ComparisonResult).where(ComparisonResult.execution_id == execution_id)
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    # 收集目标执行下的所有回放子执行，删除父执行前必须先清理这些外键引用。
    async def _collect_child_execution_ids(self, execution_id: UUID) -> list[UUID]:
        """Collect replay executions that reference the target execution."""
        collected: list[UUID] = []
        pending = [execution_id]
        while pending:
            parent_id = pending.pop(0)
            result = await self.session.execute(
                select(ExecutionJob.id).where(ExecutionJob.parent_execution_id == parent_id)
            )
            child_ids = list(result.scalars().all())
            for child_id in child_ids:
                if child_id not in collected:
                    collected.append(child_id)
                    pending.append(child_id)
        return collected

    # 删除执行及其子执行关联的回放任务和比对结果，避免父执行删除时触发外键约束。
    async def _delete_replay_dependencies_for_executions(self, execution_ids: list[UUID]) -> int:
        if not execution_ids:
            return 0

        replay_task_result = await self.session.execute(
            select(ReplayTask.id).where(
                ReplayTask.original_execution_id.in_(execution_ids)
                | ReplayTask.replay_execution_id.in_(execution_ids)
            )
        )
        replay_task_ids = list(replay_task_result.scalars().all())
        if not replay_task_ids:
            return 0

        await self.session.execute(
            update(ReplayTask)
            .where(ReplayTask.id.in_(replay_task_ids))
            .values(comparison_id=None)
        )
        await self.session.execute(
            delete(ComparisonResult).where(
                ComparisonResult.replay_task_id.in_(replay_task_ids)
                | ComparisonResult.execution_id.in_(execution_ids)
            )
        )
        result = await self.session.execute(delete(ReplayTask).where(ReplayTask.id.in_(replay_task_ids)))
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
            child_execution_ids = await self._collect_child_execution_ids(execution_id)
            execution_ids = [execution_id, *child_execution_ids]
            await self._delete_replay_dependencies_for_executions(execution_ids)
            await self._delete_comparisons_for_execution(execution_id)
            if child_execution_ids:
                await self.session.execute(delete(ExecutionJob).where(ExecutionJob.id.in_(child_execution_ids)))
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

    async def get_by_batch_id(self, batch_id: str) -> List[ExecutionJob]:
        result = await self.session.execute(
            select(ExecutionJob).where(ExecutionJob.batch_id == batch_id).order_by(ExecutionJob.created_at)
        )
        return list(result.scalars().all())
