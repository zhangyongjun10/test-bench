"""Agent 服务"""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.entities.agent import Agent
from app.domain.repositories.agent_repo import AgentRepository, SQLAlchemyAgentRepository
from app.core.encryption import encryption_service
from app.models.agent import AgentCreate, AgentUpdate
from app.core.logger import logger


class AgentService:
    def __init__(self, session: AsyncSession):
        self.repo: AgentRepository = SQLAlchemyAgentRepository(session)
        self.session = session

    async def create_agent(self, request: AgentCreate) -> Agent:
        """创建 Agent"""
        agent = Agent(
            name=request.name,
            description=request.description,
            base_url=request.base_url.rstrip("/"),
            api_key_encrypted=encryption_service.encrypt(request.api_key),
            user_session=request.user_session
        )
        result = await self.repo.create(agent)
        logger.info(f"Created agent: {result.id} name={result.name}")
        return result

    async def update_agent(self, agent_id: UUID, request: AgentUpdate) -> Optional[Agent]:
        """更新 Agent"""
        agent = await self.repo.get_by_id(agent_id)
        if not agent:
            return None

        if request.name is not None:
            agent.name = request.name
        if request.description is not None:
            agent.description = request.description
        if request.base_url is not None:
            agent.base_url = request.base_url.rstrip("/")
        if request.api_key is not None:
            agent.api_key_encrypted = encryption_service.encrypt(request.api_key)
        if request.user_session is not None:
            agent.user_session = request.user_session

        result = await self.repo.update(agent)
        logger.info(f"Updated agent: {agent_id}")
        return result

    async def delete_agent(self, agent_id: UUID) -> bool:
        """删除 Agent"""
        agent = await self.repo.get_by_id(agent_id)
        if not agent:
            return False
        await self.repo.delete(agent_id)
        logger.info(f"Deleted agent: {agent_id}")
        return True

    async def get_agent(self, agent_id: UUID) -> Optional[Agent]:
        """获取 Agent"""
        return await self.repo.get_by_id(agent_id)

    async def list_agents(self, keyword: Optional[str] = None) -> List[Agent]:
        """列出 Agent"""
        return await self.repo.list_all(keyword)

    async def test_connection(self, agent_id: UUID) -> tuple[bool, str]:
        """测试 Agent 连接"""
        from app.clients.http_agent_client import HTTPAgentClient
        agent = await self.repo.get_by_id(agent_id)
        if not agent:
            return False, "Agent not found"

        api_key = encryption_service.decrypt(agent.api_key_encrypted)
        client = HTTPAgentClient(agent.base_url, api_key, user_session=agent.user_session)
        try:
            success, test_message = await client.test_connection()
            if success:
                logger.info(f"Agent connection test succeeded: {agent_id}")
                return True, test_message

            message = test_message.strip() if test_message else "Connection failed with empty diagnostic message"
            logger.warning(f"Agent connection test failed: {agent_id} message={message}")
            return False, message
        except Exception as e:
            error_message = str(e).strip() or e.__class__.__name__
            logger.error(f"Agent connection test error: {agent_id} error={error_message}")
            return False, f"Connection error: {error_message}"
