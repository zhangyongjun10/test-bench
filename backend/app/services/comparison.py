"""比对服务"""

import re
import json
import asyncio
import time
from datetime import datetime
from typing import Tuple, List, Optional, Dict, Any
from Levenshtein import distance
from app.core.logger import logger
from app.core.metrics import observe_llm_compare_duration
from app.domain.entities.comparison import ComparisonResult as ComparisonResultEntity, ComparisonStatus
from app.domain.entities.trace import Span
from app.domain.entities.scenario import Scenario
from app.domain.entities.execution import ExecutionJob
from app.domain.repositories.comparison_repo import ComparisonRepository
from app.clients.llm_client import LLMClient
from app.models.comparison import SingleToolComparison, SingleLLMComparison
from app.models.execution import ComparisonResult


# 最大重试次数
MAX_RETRIES = 3
# LLM 并发限制
MAX_CONCURRENT_LLM = 5
# 相似度阈值：>= 0.9 直接满分跳过 LLM，< 0.9 调用 LLM 语义比对
HIGH_SIM_THRESHOLD = 0.9
# 最大长度截断
MAX_CONTENT_LENGTH = 8000


def levenshtein_similarity(a: str, b: str) -> float:
    """计算 0-1 相似度，1 完全相同"""
    d = distance(a, b)
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1 - (d / max_len)


def normalize_json_content(content: str) -> str:
    """标准化 JSON 内容：去除 Markdown 包裹，解析后重新序列化排序 keys，消除格式差异"""
    if not content:
        return content

    # 去除 Markdown 代码块包裹
    content = re.sub(r'^```(?:json)?\n', '', content.strip())
    content = re.sub(r'\n```$', '', content)
    content = content.strip()

    # 如果不是 JSON 开头，直接返回
    if not (content.startswith('{') or content.startswith('[')):
        return content

    # 尝试解析并重新序列化
    try:
        parsed = json.loads(content)
        return json.dumps(parsed, sort_keys=True, ensure_ascii=False)
    except json.JSONDecodeError:
        # 解析失败返回原文
        return content


def truncate_content(content: str) -> str:
    """截断过长内容，优先保留 input"""
    if len(content) <= MAX_CONTENT_LENGTH:
        return content
    return content[:MAX_CONTENT_LENGTH - 10] + '\n[...truncated]'


def extract_llm_content(output: str) -> str:
    """从 LLM span output 中提取实际的助手回复内容
    处理格式: {"assistantTexts": [...]} 或者 {"lastAssistant": {"content": ...}}
    """
    if not output:
        return output

    # 尝试解析 JSON 并提取实际内容
    try:
        parsed = json.loads(output)
        # 处理 assistantTexts 格式
        if isinstance(parsed, dict) and 'assistantTexts' in parsed:
            texts = parsed['assistantTexts']
            if isinstance(texts, list) and len(texts) > 0:
                return '\n'.join(str(t) for t in texts if t)
        # 处理 lastAssistant.content 格式
        if isinstance(parsed, dict) and 'lastAssistant' in parsed:
            content = parsed['lastAssistant'].get('content')
            if isinstance(content, list):
                # OpenAI 格式: [{type: "text", text: "..."}]
                return '\n'.join(
                    item.get('text', '') for item in content
                    if isinstance(item, dict) and item.get('type') == 'text'
                ).strip()
            elif isinstance(content, str):
                return content
    except json.JSONDecodeError:
        # 不是 JSON，返回原文
        pass

    return output

class ComparisonService:
    """详细比对服务 - 支持过程（tool调用）+ 结果（最终LLM输出）双维度比对"""

    # Tool 调用比对 Prompt
    TOOL_COMPARE_PROMPT = """你是一个工具调用比对专家。请判断实际工具调用和基线工具调用的语义一致性。

任务要求：
- 重点判断**功能意图和参数目的**是否一致，不要纠结于措辞、格式的细微差异
- 相同的输入应当给出稳定可重复的分数
- 分数范围 0 到 1：0 = 完全不一致，1 = 完全一致

工具名称: {tool_name}

基线输入:
{baseline_input}

基线输出:
{baseline_output}

实际输入:
{actual_input}

实际输出:
{actual_output}

请严格输出 JSON 格式，不要有其他内容：
{{
  "consistent": true/false,
  "score": 0.x,
  "reason": "一两句话解释原因"
}}
"""

    # LLM 结果比对 Prompt
    RESULT_COMPARE_PROMPT = """你是一个 AI 输出比对专家。请比对实际输出和基线结果的语义一致性。

任务要求：
- 重点判断**语义和核心信息**是否一致，不要纠结于措辞、顺序、格式的细微差异
- 相同的输入应当给出稳定可重复的分数
- 分数范围 0 到 1：0 = 完全不一致，1 = 完全一致

基线输出:
{baseline}

实际输出:
{actual}

请严格输出 JSON 格式，不要有其他内容：
{{
  "consistent": true/false,
  "score": 0.x,
  "reason": "一两句话解释为什么这么打分"
}}
"""

    def __init__(self, llm_client: LLMClient, comparison_repo: ComparisonRepository):
        self.llm_client = llm_client
        self.comparison_repo = comparison_repo
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)

    async def detailed_compare(
        self,
        scenario: Scenario,
        execution: ExecutionJob,
        trace_spans: List[Span],
    ) -> ComparisonResultEntity:
        """执行详细比对：过程比对 + 结果比对"""
        # 提取 tool spans 和 llm spans
        tool_spans = [s for s in trace_spans if s.span_type == 'tool']
        llm_spans = [s for s in trace_spans if s.span_type == 'llm']

        # 解析基线
        baseline_tool_calls = None
        error_message = None
        if scenario.baseline_tool_calls:
            try:
                baseline_tool_calls = json.loads(scenario.baseline_tool_calls)
            except json.JSONDecodeError as e:
                baseline_tool_calls = None
                error_message = f'基线工具调用 JSON 解析失败: {str(e)}'
                logger.warning(error_message)

        baseline_result = scenario.baseline_result

        # 准备存储详细比对结果
        details: Dict[str, Any] = {
            'tool_comparisons': [],
            'llm_comparison': None
        }

        process_score: Optional[float] = None
        result_score: Optional[float] = None
        overall_passed = False

        # 过程比对（如果有基线）
        if baseline_tool_calls:
            process_score, tool_comparisons = await self._compare_process(
                baseline_tool_calls,
                tool_spans,
                scenario.tool_count_tolerance,
                scenario.enable_llm_verification,
            )
            process_score = process_score * 100
            details['tool_comparisons'] = tool_comparisons

        # 结果比对（如果有基线）
        if baseline_result and llm_spans:
            # 只比对最后一个 LLM 输出
            last_llm = llm_spans[-1]
            actual_output = last_llm.output or ''
            result_score, llm_comparison = await self._compare_result(
                baseline_result,
                actual_output,
                scenario.enable_llm_verification,
            )
            result_score = result_score * 100
            details['llm_comparison'] = llm_comparison

        # 判断是否通过
        if process_score is not None and result_score is not None:
            overall_passed = (
                process_score >= scenario.process_threshold and
                result_score >= scenario.result_threshold
            )
        elif process_score is not None:
            overall_passed = process_score >= scenario.process_threshold
        elif result_score is not None:
            overall_passed = result_score >= scenario.result_threshold
        else:
            # 没有任何基线，未进行比对
            overall_passed = None

        # 创建比对记录 - 需要将 Pydantic 模型转为字典才能序列化
        serializable_details = {
            'tool_comparisons': [t.model_dump() for t in details['tool_comparisons']],
            'llm_comparison': details['llm_comparison'].model_dump() if details['llm_comparison'] else None,
        }
        comparison = ComparisonResultEntity(
            execution_id=execution.id,
            scenario_id=scenario.id,
            trace_id=execution.trace_id,
            process_score=process_score,
            result_score=result_score,
            overall_passed=overall_passed,
            details_json=json.dumps(serializable_details, ensure_ascii=False),
            status=ComparisonStatus.COMPLETED,
            error_message=error_message,
            retry_count=0,
            completed_at=datetime.utcnow(),
        )

        return comparison

    async def _compare_process(
        self,
        baseline_tools: List[Dict[str, Any]],
        actual_tools: List[Span],
        tool_count_tolerance: int,
        enable_llm_verification: bool,
    ) -> Tuple[float, List[SingleToolComparison]]:
        """过程比对：比对所有 tool 调用"""
        baseline_count = len(baseline_tools)
        actual_count = len(actual_tools)
        count_diff = abs(actual_count - baseline_count)

        # 如果次数差异超过容忍度，全部得 0 分
        if count_diff > tool_count_tolerance:
            comparisons = []
            for actual in actual_tools:
                comparisons.append(SingleToolComparison(
                    tool_name=actual.name,
                    baseline_input='',
                    baseline_output='',
                    actual_input=actual.input or '',
                    actual_output=actual.output or '',
                    similarity=0.0,
                    score=0.0,
                    consistent=False,
                    reason=f'工具数量差异超出容忍范围（基线 {baseline_count}, 实际 {actual_count}, 容忍 {tool_count_tolerance}）',
                    matched=False,
                ))
            for baseline in baseline_tools:
                if len(comparisons) < baseline_count:
                    comparisons.append(SingleToolComparison(
                        tool_name=baseline.get('name', ''),
                        baseline_input=baseline.get('input', ''),
                        baseline_output=baseline.get('output', ''),
                        actual_input='',
                        actual_output='',
                        similarity=0.0,
                        score=0.0,
                        consistent=False,
                        reason='未匹配到实际工具调用',
                        matched=False,
                    ))
            return 0.0, comparisons

        # 贪心最优匹配
        comparisons: List[SingleToolComparison] = []
        matched_baseline = [False] * len(baseline_tools)

        # 对每个实际工具，找到最相似的未匹配基线工具
        for actual in actual_tools:
            best_score = -1.0
            best_idx = -1
            best_sim = 0.0

            actual_name = actual.name
            actual_input = normalize_json_content(str(actual.input or ''))
            actual_output = normalize_json_content(str(actual.output or ''))
            actual_input = truncate_content(actual_input)
            actual_output = truncate_content(actual_output)

            for i, baseline in enumerate(baseline_tools):
                if matched_baseline[i]:
                    continue

                baseline_name = baseline.get('name', '')
                # 工具名称不同，直接跳过
                if baseline_name != actual_name:
                    continue

                baseline_input = normalize_json_content(str(baseline.get('input', '')))
                baseline_output = normalize_json_content(str(baseline.get('output', '')))
                baseline_input = truncate_content(baseline_input)
                baseline_output = truncate_content(baseline_output)

                # 计算相似度
                sim_input = levenshtein_similarity(actual_input, baseline_input)
                sim_output = levenshtein_similarity(actual_output, baseline_output)
                sim = (sim_input + sim_output) / 2

                if sim > best_score:
                    best_score = sim
                    best_sim = sim
                    best_idx = i

            if best_idx >= 0:
                # 找到匹配
                matched_baseline[best_idx] = True
                baseline = baseline_tools[best_idx]
                baseline_name = baseline.get('name', '')
                baseline_input = normalize_json_content(str(baseline.get('input', '')))
                baseline_output = normalize_json_content(str(baseline.get('output', '')))
                baseline_input = truncate_content(baseline_input)
                baseline_output = truncate_content(baseline_output)

                score, consistent, reason = await self._get_tool_score(
                    baseline_name,
                    baseline_input, baseline_output,
                    actual_input, actual_output,
                    best_sim,
                    enable_llm_verification,
                )

                comparisons.append(SingleToolComparison(
                    tool_name=actual_name,
                    baseline_input=baseline_input,
                    baseline_output=baseline_output,
                    actual_input=actual_input,
                    actual_output=actual_output,
                    similarity=best_sim,
                    score=score,
                    consistent=consistent,
                    reason=reason,
                    matched=True,
                ))
            else:
                # 没有找到匹配
                comparisons.append(SingleToolComparison(
                    tool_name=actual_name,
                    baseline_input='',
                    baseline_output='',
                    actual_input=actual_input,
                    actual_output=actual_output,
                    similarity=0.0,
                    score=0.0,
                    consistent=False,
                    reason='未找到匹配的基线工具',
                    matched=False,
                ))

        # 处理未匹配的基线
        for i, baseline in enumerate(baseline_tools):
            if not matched_baseline[i]:
                baseline_name = baseline.get('name', '')
                baseline_input = normalize_json_content(str(baseline.get('input', '')))
                baseline_output = normalize_json_content(str(baseline.get('output', '')))
                baseline_input = truncate_content(baseline_input)
                baseline_output = truncate_content(baseline_output)

                comparisons.append(SingleToolComparison(
                    tool_name=baseline_name,
                    baseline_input=baseline_input,
                    baseline_output=baseline_output,
                    actual_input='',
                    actual_output='',
                    similarity=0.0,
                    score=0.0,
                    consistent=False,
                    reason='基线工具未找到实际匹配',
                    matched=False,
                ))

        # 计算平均分
        if not comparisons:
            return 0.0, []
        avg_score = sum(c.score for c in comparisons) / len(comparisons)
        return avg_score, comparisons

    async def _get_tool_score(
        self,
        tool_name: str,
        baseline_input: str,
        baseline_output: str,
        actual_input: str,
        actual_output: str,
        similarity: float,
        enable_llm_verification: bool,
    ) -> Tuple[float, bool, str]:
        """获取单个 tool 的分数：两阶段策略"""
        # 高相似度直接满分
        if similarity > HIGH_SIM_THRESHOLD:
            return 1.0, True, f'算法相似度 {similarity:.3f} > {HIGH_SIM_THRESHOLD}，跳过 LLM 验证'

        # 关闭 LLM 验证，直接用算法相似度
        if not enable_llm_verification:
            return similarity, similarity > 0.5, f'LLM 验证已关闭，使用算法相似度 {similarity:.3f}'

        # 相似度 <= 0.9，调用 LLM 验证
        async with self._semaphore:
            for attempt in range(MAX_RETRIES):
                try:
                    prompt = self.TOOL_COMPARE_PROMPT.format(
                        tool_name=tool_name,
                        baseline_input=baseline_input,
                        baseline_output=baseline_output,
                        actual_input=actual_input,
                        actual_output=actual_output,
                    )
                    start_time = time.time()
                    # 注意：compare 已经包含了 prompt 构建、调用、解析全流程
                    score, consistent, reason = await self.llm_client.compare(prompt, "", "")
                    duration = time.time() - start_time
                    observe_llm_compare_duration(duration)
                    logger.debug(f'Tool LLM compare done: {tool_name}, score={score}')
                    return score, consistent, reason
                except Exception as e:
                    if attempt == MAX_RETRIES - 1:
                        logger.error(f'LLM compare failed after {MAX_RETRIES} retries: {e}')
                        return 0.0, False, f'LLM 比对失败：已重试 {MAX_RETRIES} 次，错误: {str(e)}'
                # 指数退避
                await asyncio.sleep(2 ** attempt)

        return 0.0, False, '重试耗尽仍失败'

    async def _compare_result(
        self,
        baseline: str,
        actual: str,
        enable_llm_verification: bool,
    ) -> Tuple[float, SingleLLMComparison]:
        """结果比对：比对最后一个 LLM 输出"""
        # 提取实际的 LLM 内容（处理包装在 JSON 中的情况）
        actual = extract_llm_content(actual)
        # JSON 标准化
        baseline_norm = normalize_json_content(baseline)
        actual_norm = normalize_json_content(actual)
        baseline_norm = truncate_content(baseline_norm)
        actual_norm = truncate_content(actual_norm)

        # 算法相似度
        similarity = levenshtein_similarity(baseline_norm, actual_norm)

        # 高相似度直接满分
        if similarity > HIGH_SIM_THRESHOLD:
            score = 1.0
            consistent = True
            reason = f'算法相似度 {similarity:.3f} > {HIGH_SIM_THRESHOLD}，跳过 LLM 验证'
        # 关闭 LLM 验证，直接用算法相似度
        elif not enable_llm_verification:
            score = similarity
            consistent = similarity > 0.5
            reason = f'LLM 验证已关闭，使用算法相似度 {similarity:.3f}'
        # 相似度 <= 0.9，调用 LLM 验证
        else:
            score = 0.0
            consistent = False
            reason = f'LLM 比对失败：已重试 {MAX_RETRIES} 次'
            for attempt in range(MAX_RETRIES):
                try:
                    prompt = self.RESULT_COMPARE_PROMPT.format(
                        baseline=baseline_norm,
                        actual=actual_norm,
                    )
                    start_time = time.time()
                    # 注意：compare 已经包含了 prompt 构建、调用、解析全流程
                    score, consistent, reason = await self.llm_client.compare(prompt, actual_norm, baseline_norm)
                    duration = time.time() - start_time
                    observe_llm_compare_duration(duration)
                    logger.debug('Result LLM compare done')
                    break
                except Exception as e:
                    if attempt == MAX_RETRIES - 1:
                        logger.error(f'Result LLM compare failed after {MAX_RETRIES} retries: {e}')
                        score = 0.0
                        consistent = False
                        reason = f'LLM 比对失败：已重试 {MAX_RETRIES} 次，错误: {str(e)}'
                await asyncio.sleep(2 ** attempt)

        comparison = SingleLLMComparison(
            baseline_output=baseline_norm,
            actual_output=actual_norm,
            similarity=similarity,
            score=score,
            consistent=consistent,
            reason=reason,
        )
        return score, comparison

    # 保持原有 compare 方法向后兼容
    async def compare(
        self,
        question: str,
        actual: str,
        baseline: str
    ) -> ComparisonResult:
        """比对结果（兼容旧接口）"""
        start_time = time.time()
        prompt = self.RESULT_COMPARE_PROMPT.format(
            baseline=baseline,
            actual=actual,
        )

        try:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await self.llm_client.chat_completion(prompt)
                    result = json.loads(response)
                    score = float(result.get('score', 0.0))
                    passed = bool(result.get('consistent', False))
                    reason = str(result.get('reason', 'LLM 验证完成'))

                    duration = time.time() - start_time
                    observe_llm_compare_duration(duration)
                    logger.info(f"Comparison completed: score={score} passed={passed} duration={duration:.2f}s")

                    return ComparisonResult(
                        score=score,
                        passed=passed,
                        reason=reason
                    )
                except (json.JSONDecodeError, ValueError) as e:
                    if attempt == MAX_RETRIES - 1:
                        raise e
                await asyncio.sleep(2 ** attempt)

            return ComparisonResult(
                score=0.0,
                passed=False,
                reason=f"Comparison failed after {MAX_RETRIES} retries"
            )
        except Exception as e:
            duration = time.time() - start_time
            observe_llm_compare_duration(duration)
            logger.error(f"Comparison failed: {e}")
            return ComparisonResult(
                score=0.0,
                passed=False,
                reason=f"Comparison error: {str(e)}"
            )
