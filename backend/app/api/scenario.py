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
    try:
        scenario = await service.create_scenario(request)
        return Response[ScenarioResponse](
            data=ScenarioResponse.model_validate(scenario)
        )
    except ValueError as e:
        return Response(code=1, message=str(e), data=None)


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
    try:
        scenario = await service.update_scenario(scenario_id, request)
        if not scenario:
            return Response(code=404, message="Scenario not found", data=None)
        return Response[ScenarioResponse](
            data=ScenarioResponse.model_validate(scenario)
        )
    except ValueError as e:
        return Response(code=1, message=str(e), data=None)


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


@router.post("/{scenario_id}/set-baseline/{execution_id}")
async def set_baseline_from_execution(
    scenario_id: UUID,
    execution_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> Response[None]:
    """从指定执行提取基线，设置为场景基线"""
    from app.domain.repositories.execution_repo import SQLAlchemyExecutionRepository
    from app.domain.repositories.scenario_repo import SQLAlchemyScenarioRepository
    from app.services.trace_fetcher import TraceFetcherImpl
    import json

    execution_repo = SQLAlchemyExecutionRepository(session)
    scenario_repo = SQLAlchemyScenarioRepository(session)

    execution = await execution_repo.get_by_id(execution_id)
    if not execution:
        return Response(code=404, message="Execution not found", data=None)

    scenario = await scenario_repo.get_by_id(scenario_id)
    if not scenario:
        return Response(code=404, message="Scenario not found", data=None)

    # 获取 trace 中的所有 tool spans
    trace_fetcher = TraceFetcherImpl(session)
    spans = await trace_fetcher.fetch_spans(execution.trace_id)

    # 提取纯净内容函数：处理各种 metadata 包装格式，返回纯净文本
    # 输入可以是字符串、dict、None
    def extract_clean_content(input_content) -> str:
        if input_content is None:
            return ''
        if isinstance(input_content, str) and not input_content:
            return input_content

        js = None
        if isinstance(input_content, str):
            try:
                js = json.loads(input_content)
                # 处理双重编码：如果第一次解析得到字符串，再尝试解析一次
                if isinstance(js, str):
                    try:
                        js = json.loads(js)
                    except json.JSONDecodeError:
                        # 二次解析失败，继续用原字符串对应的js
                        pass
            except json.JSONDecodeError:
                # 不是 JSON，直接返回原字符串
                return input_content
        else:
            # 已经是 dict/object，直接使用
            js = input_content

        extracted = None

        # Case 1: {lastAssistant: {content: ...}} 格式
        if isinstance(js, dict) and js.get('lastAssistant') and isinstance(js['lastAssistant'], dict):
            content_inner = js['lastAssistant'].get('content')
            if content_inner:
                if isinstance(content_inner, list):
                    text_parts = [
                        item.get('text', '')
                        for item in content_inner
                        if item.get('type') == 'text' and item.get('text')
                    ]
                    if text_parts:
                        extracted = '\n'.join(text_parts)
                elif isinstance(content_inner, str):
                    extracted = content_inner
                elif isinstance(content_inner, dict) or isinstance(content_inner, list):
                    extracted = json.dumps(content_inner, ensure_ascii=False, indent=2)
            if extracted:
                return extracted
        # Case 2: {assistantTexts: [...]} 格式
        if isinstance(js, dict) and js.get('assistantTexts') and isinstance(js['assistantTexts'], list):
            text_parts = []
            for item in js['assistantTexts']:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict) and item.get('text'):
                    text_parts.append(item.get('text', ''))
            if text_parts:
                extracted = '\n'.join(text_parts)
                return extracted
        # Case 3: OpenAI 格式 {choices: [{message: {content: ...}}]}
        if isinstance(js, dict) and js.get('choices') and isinstance(js['choices'], list):
            for choice in js['choices']:
                if isinstance(choice, dict) and choice.get('message') and isinstance(choice['message'], dict):
                    content_inner = choice['message'].get('content')
                    if content_inner and isinstance(content_inner, str):
                        extracted = content_inner
                        return extracted
        # Case 4: 直接 {content: ...} 顶级格式
        if isinstance(js, dict) and js.get('content') is not None:
            content_inner = js.get('content')
            if isinstance(content_inner, str) and content_inner:
                extracted = content_inner
                return extracted
            elif isinstance(content_inner, list):
                text_parts = [
                    item.get('text', '')
                    for item in content_inner
                    if item.get('type') == 'text' and item.get('text')
                ]
                if text_parts:
                    extracted = '\n'.join(text_parts)
                    return extracted
        # 没有可提取的，返回原输入
        if isinstance(input_content, str):
            return input_content
        else:
            return json.dumps(input_content, ensure_ascii=False)

    # 提取 tool calls
    # LLM-only mode no longer extracts or stores baseline_tool_calls.

    # 提取最终 llm output
    # 优先使用 execution.original_response（执行返回的最终结果），如果没有再去 trace 找
    last_llm_output = None
    if execution.original_response:
        last_llm_output = extract_clean_content(execution.original_response)
    else:
        # 如果没有 original_response，从 trace 最后一个 llm span 提取
        llm_spans = [s for s in spans if s.span_type == 'llm']
        if llm_spans:
            output = llm_spans[-1].output
            last_llm_output = extract_clean_content(output)

    # 更新场景基线
    scenario.baseline_result = last_llm_output
    await scenario_repo.update(scenario)

    return Response[None](code=0, message="Baseline set successfully", data=None)
