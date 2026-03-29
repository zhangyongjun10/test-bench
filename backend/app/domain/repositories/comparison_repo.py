"""比对结果仓储"""

from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.entities.comparison import ComparisonResult, ComparisonStatus


class ComparisonRepository(ABC):
    """比对结果仓储接口"""

    @abstractmethod
    async def create(self, session: AsyncSession, comparison: ComparisonResult) -> ComparisonResult:
        """创建比对记录"""
        pass

    @abstractmethod
    async def get_by_execution_id(self, session: AsyncSession, execution_id: UUID) -> Optional[ComparisonResult]:
        """获取执行最新的比对结果"""
        pass

    @abstractmethod
    async def update(self, session: AsyncSession, comparison: ComparisonResult) -> ComparisonResult:
        """更新比对记录"""
        pass


class SQLAlchemyComparisonRepository(ComparisonRepository):
    """SQLAlchemy 实现比对结果仓储"""

    async def create(self, session: AsyncSession, comparison: ComparisonResult) -> ComparisonResult:
        """创建比对记录"""
        session.add(comparison)
        await session.commit()
        await session.refresh(comparison)
        return comparison

    async def get_by_execution_id(self, session: AsyncSession, execution_id: UUID) -> Optional[ComparisonResult]:
        """获取执行最新的比对结果"""
        stmt = (
            select(ComparisonResult)
            .where(ComparisonResult.execution_id == execution_id)
            .order_by(ComparisonResult.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, session: AsyncSession, comparison: ComparisonResult) -> ComparisonResult:
        """更新比对记录"""
        await session.commit()
        await session.refresh(comparison)
        return comparison
