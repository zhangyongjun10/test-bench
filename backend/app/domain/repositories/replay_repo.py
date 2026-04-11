"""Replay task repository."""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.replay import ReplayTask, ReplayTaskStatus


class SQLAlchemyReplayRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, replay_task: ReplayTask, *, commit: bool = True) -> ReplayTask:
        self.session.add(replay_task)
        if commit:
            await self.session.commit()
            await self.session.refresh(replay_task)
        return replay_task

    async def update(self, replay_task: ReplayTask, *, commit: bool = True) -> ReplayTask:
        self.session.add(replay_task)
        if commit:
            await self.session.commit()
            await self.session.refresh(replay_task)
        return replay_task

    async def get_by_id(self, replay_task_id: UUID) -> Optional[ReplayTask]:
        result = await self.session.execute(
            select(ReplayTask).where(ReplayTask.id == replay_task_id)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, idempotency_key: str) -> Optional[ReplayTask]:
        result = await self.session.execute(
            select(ReplayTask).where(ReplayTask.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def list_by_original_execution(
        self,
        original_execution_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[int, list[ReplayTask]]:
        count_result = await self.session.execute(
            select(func.count())
            .select_from(ReplayTask)
            .where(ReplayTask.original_execution_id == original_execution_id)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(ReplayTask)
            .where(ReplayTask.original_execution_id == original_execution_id)
            .order_by(ReplayTask.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return total, list(result.scalars().all())

    async def claim_queued(self, replay_task_id: UUID) -> bool:
        stmt = (
            update(ReplayTask)
            .where(
                ReplayTask.id == replay_task_id,
                ReplayTask.status == ReplayTaskStatus.QUEUED,
            )
            .values(status=ReplayTaskStatus.RUNNING)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return (result.rowcount or 0) == 1
