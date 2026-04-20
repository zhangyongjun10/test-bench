"""System API"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.db import get_db
from app.core.encryption import encryption_service
from app.models.common import Response
from app.models.system import (
    ClickHouseConfigUpdate,
    ClickHouseConfigResponse,
    ClickHouseTestResponse,
    RuntimeConfigResponse,
)
from app.config import settings
from app.domain.entities.system import SystemClickhouseConfig
from app.clients.clickhouse_client import ClickHouseClient


# 系统配置路由，集中处理运行时配置和 ClickHouse 连接配置。
router = APIRouter(prefix="/api/v1/system", tags=["system"])


# 获取前端运行时需要的非敏感系统配置，避免前端重复维护后端环境变量默认值。
@router.get("/runtime-config")
async def get_runtime_config() -> Response[RuntimeConfigResponse]:
    return Response[RuntimeConfigResponse](
        data=RuntimeConfigResponse(
            concurrent_execution_max_concurrency=settings.concurrent_execution_max_concurrency
        )
    )


@router.get("/clickhouse")
async def get_clickhouse_config(
    session: AsyncSession = Depends(get_db)
) -> Response[ClickHouseConfigResponse]:
    """获取 ClickHouse 配置"""
    result = await session.execute(select(SystemClickhouseConfig).where(SystemClickhouseConfig.id == 1))
    config = result.scalar_one_or_none()
    if not config:
        return Response(code=404, message="Not configured", data=None)
    return Response[ClickHouseConfigResponse](
        data=ClickHouseConfigResponse(
            endpoint=config.endpoint,
            database=config.database,
            username=config.username,
            source_type=config.source_type
        )
    )


@router.post("/clickhouse")
async def update_clickhouse_config(
    request: ClickHouseConfigUpdate,
    session: AsyncSession = Depends(get_db)
) -> Response[ClickHouseConfigResponse]:
    """更新 ClickHouse 配置"""
    result = await session.execute(select(SystemClickhouseConfig).where(SystemClickhouseConfig.id == 1))
    config = result.scalar_one_or_none()

    if not config:
        config = SystemClickhouseConfig(id=1)

    config.endpoint = request.endpoint
    config.database = request.database
    config.username = request.username
    if request.password:
        config.password_encrypted = encryption_service.encrypt(request.password)
    config.source_type = request.source_type

    session.add(config)
    await session.commit()
    await session.refresh(config)

    return Response[ClickHouseConfigResponse](
        data=ClickHouseConfigResponse(
            endpoint=config.endpoint,
            database=config.database,
            username=config.username,
            source_type=config.source_type
        )
    )


@router.post("/clickhouse/test")
async def test_clickhouse_connection(
    request: ClickHouseConfigUpdate,
    session: AsyncSession = Depends(get_db)
) -> Response[ClickHouseTestResponse]:
    """测试 ClickHouse 连接"""
    password = request.password
    if not password:
        # 如果没提供新密码，从数据库读取
        result = await session.execute(select(SystemClickhouseConfig).where(SystemClickhouseConfig.id == 1))
        existing = result.scalar_one_or_none()
        if existing and existing.password_encrypted:
            password = encryption_service.decrypt(existing.password_encrypted)

    client = ClickHouseClient(
        endpoint=request.endpoint,
        database=request.database,
        username=request.username,
        password=password
    )
    success = client.test_connection()
    client.close()

    if success:
        return Response[ClickHouseTestResponse](
            data=ClickHouseTestResponse(success=True, message="Connection successful")
        )
    else:
        return Response[ClickHouseTestResponse](
            data=ClickHouseTestResponse(success=False, message="Connection failed")
        )
