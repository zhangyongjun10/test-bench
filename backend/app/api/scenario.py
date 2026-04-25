"""Scenario API。"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.common import Response
from app.models.scenario import ScenarioCreate, ScenarioResponse, ScenarioUpdate
from app.services.scenario_service import ScenarioService

router = APIRouter(prefix="/api/v1/scenario", tags=["scenario"])


@router.post("")
async def create_scenario(
    request: ScenarioCreate,
    session: AsyncSession = Depends(get_db),
) -> Response[ScenarioResponse]:
    """创建单条 Case，并把多选 Agent 作为同一记录的关联集合保存。"""

    service = ScenarioService(session)
    try:
        scenario = await service.create_scenario(request)
        return Response[ScenarioResponse](data=scenario)
    except ValueError as error:
        return Response(code=1, message=str(error), data=None)


@router.get("")
async def list_scenarios(
    agent_id: Optional[UUID] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> Response[list[ScenarioResponse]]:
    """列出 Case；传入 Agent 时仅返回与该 Agent 存在关联的记录。"""

    service = ScenarioService(session)
    scenarios = await service.list_scenarios(keyword, agent_id)
    return Response[list[ScenarioResponse]](data=scenarios)


@router.get("/{scenario_id}")
async def get_scenario(
    scenario_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> Response[ScenarioResponse]:
    """获取单条 Case 详情，并补齐所属 Agent 列表。"""

    service = ScenarioService(session)
    scenario = await service.get_scenario(scenario_id)
    if not scenario:
        return Response(code=404, message="Scenario not found", data=None)
    return Response[ScenarioResponse](data=scenario)


@router.put("/{scenario_id}")
async def update_scenario(
    scenario_id: UUID,
    request: ScenarioUpdate,
    session: AsyncSession = Depends(get_db),
) -> Response[ScenarioResponse]:
    """更新 Case 内容，并在需要时整组替换 Agent 绑定。"""

    service = ScenarioService(session)
    try:
        scenario = await service.update_scenario(scenario_id, request)
        if not scenario:
            return Response(code=404, message="Scenario not found", data=None)
        return Response[ScenarioResponse](data=scenario)
    except ValueError as error:
        return Response(code=1, message=str(error), data=None)


@router.delete("/{scenario_id}")
async def delete_scenario(
    scenario_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> Response[None]:
    """物理删除 Case；若仍被执行、比对或回放引用则返回明确错误。"""

    service = ScenarioService(session)
    try:
        success = await service.delete_scenario(scenario_id)
        if not success:
            return Response(code=404, message="Scenario not found", data=None)
        return Response[None](code=0, message="Deleted", data=None)
    except ValueError as error:
        return Response(code=1, message=str(error), data=None)


@router.post("/{scenario_id}/set-baseline/{execution_id}")
async def set_baseline_from_execution(
    scenario_id: UUID,
    execution_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> Response[None]:
    """从指定执行提取基线输出，并回写到单条 Case 主记录。"""

    import json

    from app.domain.repositories.execution_repo import SQLAlchemyExecutionRepository
    from app.domain.repositories.scenario_repo import SQLAlchemyScenarioRepository
    from app.services.trace_fetcher import TraceFetcherImpl

    execution_repo = SQLAlchemyExecutionRepository(session)
    scenario_repo = SQLAlchemyScenarioRepository(session)

    execution = await execution_repo.get_by_id(execution_id)
    if not execution:
        return Response(code=404, message="Execution not found", data=None)

    scenario = await scenario_repo.get_by_id(scenario_id)
    if not scenario:
        return Response(code=404, message="Scenario not found", data=None)

    trace_fetcher = TraceFetcherImpl(session)
    spans = await trace_fetcher.fetch_spans(execution.trace_id)

    def extract_clean_content(input_content) -> str:
        """兼容历史执行响应结构，尽量提取最终可读的 Assistant 文本。"""

        if input_content is None:
            return ""
        if isinstance(input_content, str) and not input_content:
            return input_content

        parsed_json = None
        if isinstance(input_content, str):
            try:
                parsed_json = json.loads(input_content)
                if isinstance(parsed_json, str):
                    try:
                        parsed_json = json.loads(parsed_json)
                    except json.JSONDecodeError:
                        pass
            except json.JSONDecodeError:
                return input_content
        else:
            parsed_json = input_content

        extracted = None

        if isinstance(parsed_json, dict) and parsed_json.get("lastAssistant") and isinstance(parsed_json["lastAssistant"], dict):
            content_inner = parsed_json["lastAssistant"].get("content")
            if content_inner:
                if isinstance(content_inner, list):
                    text_parts = [
                        item.get("text", "")
                        for item in content_inner
                        if item.get("type") == "text" and item.get("text")
                    ]
                    if text_parts:
                        extracted = "\n".join(text_parts)
                elif isinstance(content_inner, str):
                    extracted = content_inner
                elif isinstance(content_inner, (dict, list)):
                    extracted = json.dumps(content_inner, ensure_ascii=False, indent=2)
            if extracted:
                return extracted

        if isinstance(parsed_json, dict) and parsed_json.get("assistantTexts") and isinstance(parsed_json["assistantTexts"], list):
            text_parts = []
            for item in parsed_json["assistantTexts"]:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict) and item.get("text"):
                    text_parts.append(item.get("text", ""))
            if text_parts:
                return "\n".join(text_parts)

        if isinstance(parsed_json, dict) and parsed_json.get("choices") and isinstance(parsed_json["choices"], list):
            for choice in parsed_json["choices"]:
                if isinstance(choice, dict) and choice.get("message") and isinstance(choice["message"], dict):
                    content_inner = choice["message"].get("content")
                    if content_inner and isinstance(content_inner, str):
                        return content_inner

        if isinstance(parsed_json, dict) and parsed_json.get("content") is not None:
            content_inner = parsed_json.get("content")
            if isinstance(content_inner, str) and content_inner:
                return content_inner
            if isinstance(content_inner, list):
                text_parts = [
                    item.get("text", "")
                    for item in content_inner
                    if item.get("type") == "text" and item.get("text")
                ]
                if text_parts:
                    return "\n".join(text_parts)

        if isinstance(input_content, str):
            return input_content
        return json.dumps(input_content, ensure_ascii=False)

    last_llm_output = None
    if execution.original_response:
        last_llm_output = extract_clean_content(execution.original_response)
    else:
        llm_spans = [span for span in spans if span.span_type == "llm"]
        if llm_spans:
            last_llm_output = extract_clean_content(llm_spans[-1].output)

    scenario.baseline_result = last_llm_output
    await scenario_repo.update(scenario)

    return Response[None](code=0, message="Baseline set successfully", data=None)
