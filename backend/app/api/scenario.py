"""Scenario API"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.models.common import Response
from app.models.scenario import (
    ScenarioCreate,
    ScenarioUpdate,
    ScenarioResponse
)
from app.services.scenario_service import ScenarioService


router = APIRouter(prefix="/api/v1/scenario", tags=["scenario"])


@router.post("")
async def create_scenario(
    request: ScenarioCreate,
    session: AsyncSession = Depends(get_db)
) -> Response[ScenarioResponse]:
    """创建测试场景"""
    service = ScenarioService(session)
    scenario = await service.create_scenario(request)
    return Response[ScenarioResponse](
        data=ScenarioResponse.model_validate(scenario)
    )


@router.get("")
async def list_scenarios(
    agent_id: Optional[UUID] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    session: AsyncSession = Depends(get_db)
) -> Response[List[ScenarioResponse]]:
    """列出场景，支持搜索和 Agent 筛选，不传 agent_id 返回全部"""
    service = ScenarioService(session)
    scenarios_with_names = await service.list_scenarios(keyword, agent_id)
    response_data = []
    for scenario, agent_name in scenarios_with_names:
        data = ScenarioResponse.model_validate(scenario)
        data.agent_name = agent_name
        response_data.append(data)
    return Response[List[ScenarioResponse]](
        data=response_data
    )


@router.get("/{scenario_id}")
async def get_scenario(
    scenario_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[ScenarioResponse]:
    """获取场景详情"""
    service = ScenarioService(session)
    scenario = await service.get_scenario(scenario_id)
    if not scenario:
        return Response(code=404, message="Scenario not found", data=None)
    return Response[ScenarioResponse](
        data=ScenarioResponse.model_validate(scenario)
    )


@router.put("/{scenario_id}")
async def update_scenario(
    scenario_id: UUID,
    request: ScenarioUpdate,
    session: AsyncSession = Depends(get_db)
) -> Response[ScenarioResponse]:
    """更新场景"""
    service = ScenarioService(session)
    scenario = await service.update_scenario(scenario_id, request)
    if not scenario:
        return Response(code=404, message="Scenario not found", data=None)
    return Response[ScenarioResponse](
        data=ScenarioResponse.model_validate(scenario)
    )


@router.delete("/{scenario_id}")
async def delete_scenario(
    scenario_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[None]:
    """删除场景"""
    service = ScenarioService(session)
    success = await service.delete_scenario(scenario_id)
    if not success:
        return Response(code=404, message="Scenario not found", data=None)
    return Response[None](code=0, message="Deleted", data=None)
