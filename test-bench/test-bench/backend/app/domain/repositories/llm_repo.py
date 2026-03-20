"""LLM 模型仓储"""

from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.entities.llm import LLMModel


class LLMRepository(ABC):
    @abstractmethod
    async def create(self, model: LLMModel) -> LLMModel:
        """创建新模型"""
        pass

    @abstractmethod
    async def update(self, model: LLMModel) -> LLMModel:
        """更新模型"""
        pass

    @abstractmethod
    async def delete(self, model_id: UUID) -> None:
        """软删除模型"""
        pass

    @abstractmethod
    async def get_by_id(self, model_id: UUID) -> Optional[LLMModel]:
        """按 ID 获取"""
        pass

    @abstractmethod
    async def get_default(self) -> Optional[LLMModel]:
        """获取默认模型"""
        pass

    @abstractmethod
    async def list_all(self, keyword: Optional[str] = None) -> List[LLMModel]:
        """列表，支持搜索"""
        pass

    @abstractmethod
    async def clear_default(self) -> None:
        """清除所有默认标记"""
        pass


class SQLAlchemyLLMRepository(LLMRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, model: LLMModel) -> LLMModel:
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def update(self, model: LLMModel) -> LLMModel:
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return model

    async def delete(self, model_id: UUID) -> None:
        model = await self.get_by_id(model_id)
        if model:
            model.deleted_at = datetime.utcnow()
            await self.session.commit()

    async def get_by_id(self, model_id: UUID) -> Optional[LLMModel]:
        result = await self.session.execute(
            select(LLMModel).where(LLMModel.id == model_id, LLMModel.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_default(self) -> Optional[LLMModel]:
        result = await self.session.execute(
            select(LLMModel).where(LLMModel.is_default.is_(True), LLMModel.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_all(self, keyword: Optional[str] = None) -> List[LLMModel]:
        query = select(LLMModel).where(LLMModel.deleted_at.is_(None)).order_by(LLMModel.created_at.desc())
        if keyword:
            query = query.where(LLMModel.name.ilike(f"%{keyword}%"))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def clear_default(self) -> None:
        result = await self.session.execute(
            select(LLMModel).where(LLMModel.is_default.is_(True), LLMModel.deleted_at.is_(None))
        )
        for model in result.scalars().all():
            model.is_default = False
        await self.session.commit()
