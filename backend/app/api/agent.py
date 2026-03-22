"""Agent API"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.models.common import Response
from app.models.agent import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentTestResponse
)
from app.services.agent_service import AgentService


router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.post("")
async def create_agent(
    request: AgentCreate,
    session: AsyncSession = Depends(get_db)
) -> Response[AgentResponse]:
    """创建 Agent"""
    service = AgentService(session)
    agent = await service.create_agent(request)
    return Response[AgentResponse](
        data=AgentResponse.model_validate(agent)
    )


@router.get("")
async def list_agents(
    keyword: Optional[str] = None,
    session: AsyncSession = Depends(get_db)
) -> Response[List[AgentResponse]]:
    """列出 Agent，支持搜索"""
    service = AgentService(session)
    agents = await service.list_agents(keyword)
    return Response[List[AgentResponse]](
        data=[AgentResponse.model_validate(a) for a in agents]
    )


@router.get("/{agent_id}")
async def get_agent(
    agent_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[AgentResponse]:
    """获取 Agent 详情"""
    service = AgentService(session)
    agent = await service.get_agent(agent_id)
    if not agent:
        return Response(code=404, message="Agent not found", data=None)
    return Response[AgentResponse](
        data=AgentResponse.model_validate(agent)
    )


@router.put("/{agent_id}")
async def update_agent(
    agent_id: UUID,
    request: AgentUpdate,
    session: AsyncSession = Depends(get_db)
) -> Response[AgentResponse]:
    """更新 Agent"""
    service = AgentService(session)
    agent = await service.update_agent(agent_id, request)
    if not agent:
        return Response(code=404, message="Agent not found", data=None)
    return Response[AgentResponse](
        data=AgentResponse.model_validate(agent)
    )


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[None]:
    """删除 Agent"""
    service = AgentService(session)
    success = await service.delete_agent(agent_id)
    if not success:
        return Response(code=404, message="Agent not found", data=None)
    return Response[None](code=0, message="Deleted", data=None)


@router.post("/{agent_id}/test")
async def test_connection(
    agent_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[AgentTestResponse]:
    """测试 Agent 连接"""
    service = AgentService(session)
    success, message = await service.test_connection(agent_id)
    return Response[AgentTestResponse](
        data=AgentTestResponse(success=success, message=message)
    )
