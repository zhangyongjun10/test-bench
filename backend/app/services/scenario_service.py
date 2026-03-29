"""测试场景服务"""

from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.entities.agent import Agent
from app.domain.entities.scenario import Scenario
from app.domain.repositories.scenario_repo import ScenarioRepository, SQLAlchemyScenarioRepository
from app.models.scenario import ScenarioCreate, ScenarioUpdate
from app.core.logger import logger


class ScenarioService:
    def __init__(self, session: AsyncSession):
        self.repo: ScenarioRepository = SQLAlchemyScenarioRepository(session)
        self.session = session

    async def create_scenario(self, request: ScenarioCreate) -> Scenario:
        """创建场景"""
        scenario = Scenario(
            agent_id=request.agent_id,
            name=request.name,
            description=request.description,
            prompt=request.prompt,
            baseline_result=request.baseline_result,
            compare_result=request.compare_result,
            compare_process=request.compare_process
        )
        result = await self.repo.create(scenario)
        logger.info(f"Created scenario: {result.id} name={result.name} agent_id={request.agent_id}")
        return result

    async def update_scenario(self, scenario_id: UUID, request: ScenarioUpdate) -> Optional[Scenario]:
        """更新场景"""
        scenario = await self.repo.get_by_id(scenario_id)
        if not scenario:
            return None
        logger.info(f"Update scenario {scenario_id}: process_threshold={request.process_threshold}, result_threshold={request.result_threshold}")

        if request.agent_id is not None:
            scenario.agent_id = request.agent_id
        if request.name is not None:
            scenario.name = request.name
        if request.description is not None:
            scenario.description = request.description
        if request.prompt is not None:
            scenario.prompt = request.prompt
        if request.baseline_result is not None:
            scenario.baseline_result = request.baseline_result
        if request.baseline_tool_calls is not None:
            scenario.baseline_tool_calls = request.baseline_tool_calls
        if request.process_threshold is not None:
            scenario.process_threshold = request.process_threshold
        if request.result_threshold is not None:
            scenario.result_threshold = request.result_threshold
        if request.tool_count_tolerance is not None:
            scenario.tool_count_tolerance = request.tool_count_tolerance
        if request.compare_enabled is not None:
            scenario.compare_enabled = request.compare_enabled
        if request.enable_llm_verification is not None:
            scenario.enable_llm_verification = request.enable_llm_verification
        if request.compare_result is not None:
            scenario.compare_result = request.compare_result
        if request.compare_process is not None:
            scenario.compare_process = request.compare_process

        result = await self.repo.update(scenario)
        logger.info(f"Updated scenario: {scenario_id}")
        return result

    async def delete_scenario(self, scenario_id: UUID) -> bool:
        """删除场景"""
        scenario = await self.repo.get_by_id(scenario_id)
        if not scenario:
            return False
        await self.repo.delete(scenario_id)
        logger.info(f"Deleted scenario: {scenario_id}")
        return True

    async def get_scenario(self, scenario_id: UUID) -> Optional[Scenario]:
        """获取场景"""
        return await self.repo.get_by_id(scenario_id)

    async def list_scenarios(self, keyword: Optional[str] = None, agent_id: Optional[UUID] = None) -> List[Tuple[Scenario, Optional[str]]]:
        """列出所有场景，返回 (scenario, agent_name)"""
        scenarios = await self.repo.list_all(keyword, agent_id)

        # 获取所有 agent_id 对应的 Agent 名称
        agent_ids = list({s.agent_id for s in scenarios})
        if agent_ids:
            result = await self.session.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids), Agent.deleted_at.is_(None)))
            agent_map = {row[0]: row[1] for row in result.all()}
        else:
            agent_map = {}

        return [(s, agent_map.get(s.agent_id)) for s in scenarios]
