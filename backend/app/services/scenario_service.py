"""测试场景服务。"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.domain.entities.agent import Agent
from app.domain.entities.scenario import Scenario
from app.domain.repositories.scenario_repo import SQLAlchemyScenarioRepository, ScenarioRepository
from app.models.scenario import ScenarioCreate, ScenarioResponse, ScenarioUpdate


class ScenarioService:
    """封装 Case 的创建、编辑、删除与多 Agent 关联组装逻辑。"""

    def __init__(self, session: AsyncSession):
        """初始化仓储与数据库会话，供后续查询 Agent 绑定和 Case 数据复用。"""

        self.repo: ScenarioRepository = SQLAlchemyScenarioRepository(session)
        self.session = session

    @staticmethod
    def _normalize_agent_ids(agent_ids: list[UUID]) -> list[UUID]:
        """按原始顺序去重 Agent 主键，避免多选控件重复值写入中间表。"""

        return list(dict.fromkeys(agent_ids))

    async def _ensure_agents_exist(self, agent_ids: list[UUID]) -> None:
        """校验所有 Agent 都存在且未删除，避免创建出无法执行的悬挂关联。"""

        unique_agent_ids = self._normalize_agent_ids(agent_ids)
        result = await self.session.execute(
            select(Agent.id).where(Agent.id.in_(unique_agent_ids), Agent.deleted_at.is_(None))
        )
        existing_agent_ids = {row[0] for row in result.all()}
        missing_agent_ids = [str(agent_id) for agent_id in unique_agent_ids if agent_id not in existing_agent_ids]
        if missing_agent_ids:
            raise ValueError(f"Agent not found: {', '.join(missing_agent_ids)}")

    async def _build_response(self, scenario: Scenario) -> ScenarioResponse:
        """把主记录与 Agent 绑定拼装成统一响应，供列表和详情页复用。"""

        bindings = await self.repo.get_agent_bindings([scenario.id])
        agent_bindings = bindings.get(scenario.id, [])
        return ScenarioResponse(
            id=scenario.id,
            agent_ids=[agent_id for agent_id, _ in agent_bindings],
            agent_names=[agent_name for _, agent_name in agent_bindings],
            name=scenario.name,
            description=scenario.description,
            prompt=scenario.prompt,
            baseline_result=scenario.baseline_result,
            llm_count_min=scenario.llm_count_min,
            llm_count_max=scenario.llm_count_max,
            compare_enabled=scenario.compare_enabled,
            created_at=scenario.created_at,
            updated_at=scenario.updated_at,
        )

    async def create_scenario(self, request: ScenarioCreate) -> ScenarioResponse:
        """创建单条 Case 主记录，并一次性写入完整 Agent 关联集合。"""

        agent_ids = self._normalize_agent_ids(request.agent_ids)
        await self._ensure_agents_exist(agent_ids)

        scenario = Scenario(
            name=request.name,
            description=request.description,
            prompt=request.prompt,
            baseline_result=request.baseline_result,
            llm_count_min=request.llm_count_min,
            llm_count_max=request.llm_count_max,
            compare_enabled=request.compare_enabled,
        )
        created_scenario = await self.repo.create(scenario)
        await self.repo.replace_agents(created_scenario.id, agent_ids)
        logger.info("Created scenario: %s name=%s agent_count=%s", created_scenario.id, request.name, len(agent_ids))
        return await self._build_response(created_scenario)

    async def update_scenario(self, scenario_id: UUID, request: ScenarioUpdate) -> Optional[ScenarioResponse]:
        """更新 Case 内容与 Agent 集合，整组覆盖以保持表单与存储一致。"""

        scenario = await self.repo.get_by_id(scenario_id)
        if not scenario:
            return None

        new_llm_count_min = request.llm_count_min if request.llm_count_min is not None else scenario.llm_count_min
        new_llm_count_max = request.llm_count_max if request.llm_count_max is not None else scenario.llm_count_max
        if new_llm_count_min > new_llm_count_max:
            raise ValueError("llm_count_min must be less than or equal to llm_count_max")

        if request.name is not None:
            scenario.name = request.name
        if request.description is not None:
            scenario.description = request.description
        if request.prompt is not None:
            scenario.prompt = request.prompt
        if request.baseline_result is not None:
            scenario.baseline_result = request.baseline_result
        if request.llm_count_min is not None:
            scenario.llm_count_min = request.llm_count_min
        if request.llm_count_max is not None:
            scenario.llm_count_max = request.llm_count_max
        if request.compare_enabled is not None:
            scenario.compare_enabled = request.compare_enabled

        result = await self.repo.update(scenario)
        if request.agent_ids is not None:
            agent_ids = self._normalize_agent_ids(request.agent_ids)
            await self._ensure_agents_exist(agent_ids)
            await self.repo.replace_agents(scenario_id, agent_ids)

        logger.info("Updated scenario: %s", scenario_id)
        return await self._build_response(result)

    async def delete_scenario(self, scenario_id: UUID) -> bool:
        """删除 Case 前先确认记录存在，避免前端误报成功。"""

        scenario = await self.repo.get_by_id(scenario_id)
        if not scenario:
            return False
        await self.repo.delete(scenario_id)
        logger.info("Deleted scenario: %s", scenario_id)
        return True

    async def get_scenario(self, scenario_id: UUID) -> Optional[ScenarioResponse]:
        """获取单条 Case 详情，并补齐多 Agent 展示字段。"""

        scenario = await self.repo.get_by_id(scenario_id)
        if not scenario:
            return None
        return await self._build_response(scenario)

    async def list_scenarios(
        self,
        keyword: Optional[str] = None,
        agent_id: Optional[UUID] = None,
    ) -> list[ScenarioResponse]:
        """列出 Case 列表，并把 Agent 绑定聚合成单条记录的展示结构。"""

        scenarios = await self.repo.list_all(keyword, agent_id)
        if not scenarios:
            return []

        bindings = await self.repo.get_agent_bindings([scenario.id for scenario in scenarios])
        response: list[ScenarioResponse] = []
        for scenario in scenarios:
            agent_bindings = bindings.get(scenario.id, [])
            response.append(
                ScenarioResponse(
                    id=scenario.id,
                    agent_ids=[agent_value for agent_value, _ in agent_bindings],
                    agent_names=[agent_name for _, agent_name in agent_bindings],
                    name=scenario.name,
                    description=scenario.description,
                    prompt=scenario.prompt,
                    baseline_result=scenario.baseline_result,
                    llm_count_min=scenario.llm_count_min,
                    llm_count_max=scenario.llm_count_max,
                    compare_enabled=scenario.compare_enabled,
                    created_at=scenario.created_at,
                    updated_at=scenario.updated_at,
                )
            )
        return response
