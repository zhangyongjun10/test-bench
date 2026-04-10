"""Comparison result repository interfaces and SQLAlchemy implementation."""

from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.comparison import ComparisonResult


class ComparisonRepository(ABC):
    """Repository interface for comparison results."""

    @abstractmethod
    async def create(self, session: AsyncSession, comparison: ComparisonResult) -> ComparisonResult:
        """Create a comparison result."""

    @abstractmethod
    async def get_by_execution_id(
        self, session: AsyncSession, execution_id: UUID
    ) -> Optional[ComparisonResult]:
        """Return the latest comparison result for an execution."""

    @abstractmethod
    async def list_by_execution_id(self, session: AsyncSession, execution_id: UUID) -> list[ComparisonResult]:
        """Return all comparison results for an execution, newest first."""

    @abstractmethod
    async def update(self, session: AsyncSession, comparison: ComparisonResult) -> ComparisonResult:
        """Persist updates to an existing comparison result."""

    @abstractmethod
    async def delete_by_execution_id(self, session: AsyncSession, execution_id: UUID) -> int:
        """Delete all comparison results for an execution."""


class SQLAlchemyComparisonRepository(ComparisonRepository):
    """SQLAlchemy-backed comparison result repository."""

    async def create(self, session: AsyncSession, comparison: ComparisonResult) -> ComparisonResult:
        session.add(comparison)
        await session.commit()
        await session.refresh(comparison)
        return comparison

    async def get_by_execution_id(
        self, session: AsyncSession, execution_id: UUID
    ) -> Optional[ComparisonResult]:
        stmt = (
            select(ComparisonResult)
            .where(ComparisonResult.execution_id == execution_id)
            .order_by(ComparisonResult.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_execution_id(self, session: AsyncSession, execution_id: UUID) -> list[ComparisonResult]:
        stmt = (
            select(ComparisonResult)
            .where(ComparisonResult.execution_id == execution_id)
            .order_by(ComparisonResult.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, session: AsyncSession, comparison: ComparisonResult) -> ComparisonResult:
        await session.commit()
        await session.refresh(comparison)
        return comparison

    async def delete_by_execution_id(self, session: AsyncSession, execution_id: UUID) -> int:
        stmt = delete(ComparisonResult).where(ComparisonResult.execution_id == execution_id)
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount or 0
