"""并发执行批次仓储。"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.execution_batch import ExecutionBatch


# 并发执行批次仓储；封装批次创建、查询和更新，供并发执行服务持久化批次级状态。
class SQLAlchemyExecutionBatchRepository:
    # 初始化批次仓储；复用调用方传入的 AsyncSession，由服务层控制连接生命周期。
    def __init__(self, session: AsyncSession):
        self.session = session

    # 创建批次记录；在后台任务启动前先落库，保证即使准备阶段全失败也能查询批次。
    async def create(self, batch: ExecutionBatch) -> ExecutionBatch:
        self.session.add(batch)
        await self.session.commit()
        await self.session.refresh(batch)
        return batch

    # 按批次 ID 查询批次记录；不存在时返回 None，批次状态接口据此区分 not_found。
    async def get_by_id(self, batch_id: str) -> Optional[ExecutionBatch]:
        return await self.session.get(ExecutionBatch, batch_id)

    # 更新批次记录；用于准备计数、启动计数和最终聚合状态落库。
    async def update(self, batch: ExecutionBatch) -> ExecutionBatch:
        self.session.add(batch)
        await self.session.commit()
        await self.session.refresh(batch)
        return batch
