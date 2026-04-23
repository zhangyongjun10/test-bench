import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  Modal,
  Result,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Tabs,
  message,
} from 'antd'
import { CopyOutlined, LeftOutlined, PushpinOutlined, ReloadOutlined } from '@ant-design/icons'

import { executionApi, llmApi, scenarioApi, scenarioApiExtended } from '../api/client'
import type {
  DetailedComparisonResult,
  ExecutionJob,
  ExecutionTrace,
  LLMModel,
  ReplayTask,
  Scenario,
} from '../api/types'

const STATUS_COLORS: Record<string, string> = {
  queued: 'blue',
  running: 'orange',
  pulling_trace: 'cyan',
  comparing: 'purple',
  completed: 'green',
  completed_with_mismatch: 'orange',
  failed: 'red',
}

const STATUS_TEXT: Record<string, string> = {
  queued: '排队中',
  running: '执行中',
  pulling_trace: '拉取 Trace',
  comparing: '结果比对',
  completed: '完成',
  completed_with_mismatch: '完成（比对未通过）',
  failed: '失败',
}

const POLL_INTERVAL = 2000
const MAX_POLL_TIME = 2 * 60 * 1000

const formatLocalTime = (value?: string | null) => {
  if (!value) {
    return '-'
  }
  const isoLikeValue = value.includes('T') ? value : value.replace(' ', 'T')
  const normalizedValue =
    /(?:Z|[+-]\d{2}:\d{2})$/.test(isoLikeValue) ? isoLikeValue : `${isoLikeValue}Z`
  const date = new Date(normalizedValue)
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

const extractDisplayOutput = (output?: string) => {
  if (!output) {
    return ''
  }

  try {
    const parsed = JSON.parse(output)
    if (parsed?.lastAssistant?.content) {
      const content = parsed.lastAssistant.content
      if (Array.isArray(content)) {
        return content
          .filter(item => item.type === 'text' && item.text)
          .map(item => item.text)
          .join('\n')
      }
      if (typeof content === 'string') {
        return content
      }
      return JSON.stringify(content, null, 2)
    }

    if (Array.isArray(parsed?.assistantTexts)) {
      return parsed.assistantTexts.join('\n')
    }

    if (Array.isArray(parsed?.choices) && parsed.choices.length > 0) {
      const firstChoice = parsed.choices[0]
      if (firstChoice?.message) {
        const message = firstChoice.message
        const textContent = extractTextContent(message.content)
        if (textContent) {
          return textContent
        }
        const toolCallSummary = extractToolCallSummary(message.tool_calls)
        if (toolCallSummary) {
          return toolCallSummary
        }
      }
    }
  } catch {
    return output
  }

  return output
}

const formatVerificationMode = (mode?: string | null) => {
  if (mode === 'algorithm_short_circuit') {
    return '算法直通'
  }
  if (mode === 'llm_verification') {
    return 'LLM 语义校验'
  }
  return mode || '-'
}

// 兼容历史比对结果里的英文原因，新比对后端会直接写中文，旧数据在页面展示时即时翻译。
const formatComparisonReason = (reason?: string | null) => {
  if (!reason) {
    return '-'
  }

  const countMismatchMatch = reason.match(
    /^LLM call count (\d+) is outside expected range (\d+) to (\d+)$/,
  )
  if (countMismatchMatch) {
    const [, actualCount, expectedMin, expectedMax] = countMismatchMatch
    return `LLM 调用次数不符合预期，实际为 ${actualCount} 次，期望范围为 ${expectedMin} ~ ${expectedMax} 次`
  }

  if (reason === 'Invalid LLM count range configuration') {
    return 'LLM 调用次数范围配置无效'
  }
  if (reason === 'Scenario baseline output is empty') {
    return '场景基线输出为空'
  }
  if (reason === 'Baseline output is empty') {
    return '基线输出为空'
  }
  if (reason === 'No final LLM output found') {
    return '未找到最终 LLM 输出'
  }

  return reason
}

const SPAN_THEME = {
  llm: {
    tagColor: 'processing',
    headerBg: '#eef6ff',
    borderColor: '#91caff',
  },
  tool: {
    tagColor: 'magenta',
    headerBg: '#fff3f0',
    borderColor: '#ffb199',
  },
  default: {
    tagColor: 'default',
    headerBg: '#f5f5f5',
    borderColor: '#d9d9d9',
  },
} as const

const getSpanTheme = (spanType?: string) => {
  if (spanType === 'llm') {
    return SPAN_THEME.llm
  }
  if (spanType === 'tool') {
    return SPAN_THEME.tool
  }
  return SPAN_THEME.default
}

const stringifyPretty = (value?: string | null) => {
  if (!value) {
    return '-'
  }
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

const extractTextContent = (content: unknown): string => {
  if (typeof content === 'string') {
    return content
  }

  if (Array.isArray(content)) {
    const textParts = content
      .map(item => {
        if (typeof item === 'string') {
          return item
        }
        if (item && typeof item === 'object' && 'type' in item && item.type === 'text' && 'text' in item) {
          return typeof item.text === 'string' ? item.text : ''
        }
        return ''
      })
      .filter(Boolean)

    if (textParts.length > 0) {
      return textParts.join('\n')
    }
  }

  return ''
}

const extractToolCallSummary = (value: unknown): string => {
  if (!Array.isArray(value) || value.length === 0) {
    return ''
  }

  const summaries = value
    .map(call => {
      if (!call || typeof call !== 'object') {
        return ''
      }

      const functionPayload =
        'function' in call && call.function && typeof call.function === 'object' ? call.function : null
      const functionName =
        functionPayload && 'name' in functionPayload && typeof functionPayload.name === 'string'
          ? functionPayload.name
          : ''
      const rawArguments =
        functionPayload && 'arguments' in functionPayload && typeof functionPayload.arguments === 'string'
          ? functionPayload.arguments
          : ''

      if (!rawArguments) {
        return functionName ? `工具调用: ${functionName}` : ''
      }

      try {
        const parsedArguments = JSON.parse(rawArguments)
        if (parsedArguments && typeof parsedArguments === 'object') {
          if ('command' in parsedArguments && typeof parsedArguments.command === 'string') {
            return parsedArguments.command
          }
          if ('path' in parsedArguments && typeof parsedArguments.path === 'string') {
            return `${functionName || '工具调用'}: ${parsedArguments.path}`
          }
        }
      } catch {
        return rawArguments
      }

      return rawArguments
    })
    .filter(Boolean)

  return summaries.join('\n')
}

const extractToolCalls = (value: unknown): Array<{ name: string; content: string }> => {
  if (!Array.isArray(value) || value.length === 0) {
    return []
  }

  return value
    .map(call => {
      if (!call || typeof call !== 'object') {
        return null
      }

      const functionPayload =
        'function' in call && call.function && typeof call.function === 'object' ? call.function : null
      const name =
        functionPayload && 'name' in functionPayload && typeof functionPayload.name === 'string'
          ? functionPayload.name
          : 'tool_call'
      const rawArguments =
        functionPayload && 'arguments' in functionPayload && typeof functionPayload.arguments === 'string'
          ? functionPayload.arguments
          : ''

      if (!rawArguments) {
        return { name, content: '' }
      }

      try {
        const parsedArguments = JSON.parse(rawArguments)
        if (parsedArguments && typeof parsedArguments === 'object') {
          if ('command' in parsedArguments && typeof parsedArguments.command === 'string') {
            return { name, content: parsedArguments.command }
          }
          return { name, content: JSON.stringify(parsedArguments, null, 2) }
        }
      } catch {
        return { name, content: rawArguments }
      }

      return { name, content: rawArguments }
    })
    .filter((item): item is { name: string; content: string } => Boolean(item))
}

const extractMessageBody = (message: unknown, fallback?: string) => {
  if (!message || typeof message !== 'object') {
    return fallback || ''
  }

  const textContent = 'content' in message ? extractTextContent(message.content) : ''
  if (textContent) {
    return textContent
  }

  const toolCallSummary = 'tool_calls' in message ? extractToolCallSummary(message.tool_calls) : ''
  if (toolCallSummary) {
    return toolCallSummary
  }

  return fallback || ''
}

const extractMessageTextOnly = (message: unknown, fallback?: string) => {
  if (!message || typeof message !== 'object') {
    return fallback || ''
  }

  const textContent = 'content' in message ? extractTextContent(message.content) : ''
  return textContent || fallback || ''
}

const extractLLMMessages = (span: ExecutionTrace['spans'][number]) => {
  const messages: Array<{
    role: string
    content: string
    toolCalls?: Array<{ name: string; content: string }>
    finishReason?: string
    showWhenEmpty?: boolean
  }> = []

  const pushMessage = (
    role: string,
    content?: string | null,
    toolCalls?: Array<{ name: string; content: string }>,
    finishReason?: string,
    showWhenEmpty?: boolean,
  ) => {
    const text = (content || '').trim()
    const calls = toolCalls || []
    if (!text && calls.length === 0 && !showWhenEmpty) {
      return
    }
    messages.push({ role, content: text, toolCalls: calls, finishReason, showWhenEmpty })
  }

  if (span.input) {
    try {
      const parsed = JSON.parse(span.input)
      if (Array.isArray(parsed)) {
        for (const item of parsed) {
          if (item && typeof item === 'object') {
            const role = typeof item.role === 'string' ? item.role : 'input'
            const toolCalls = 'tool_calls' in item ? extractToolCalls(item.tool_calls) : []
            const content =
              toolCalls.length > 0
                ? extractMessageTextOnly(item)
                : extractMessageBody(item, stringifyPretty(JSON.stringify(item)))
            pushMessage(role, content, toolCalls)
          }
        }
      } else if (parsed && typeof parsed === 'object') {
        if (typeof parsed.systemPrompt === 'string') {
          pushMessage('system', parsed.systemPrompt)
        }
        if (typeof parsed.prompt === 'string') {
          pushMessage('user', parsed.prompt)
        }
      }
    } catch {
      pushMessage('input', span.input)
    }
  }

  if (span.output) {
    let outputHandled = false
    try {
      const parsedOutput = JSON.parse(span.output)
      if (parsedOutput && typeof parsedOutput === 'object' && 'choices' in parsedOutput && Array.isArray(parsedOutput.choices)) {
        const firstChoice = parsedOutput.choices[0]
        if (firstChoice && typeof firstChoice === 'object' && 'message' in firstChoice) {
          const message = firstChoice.message
          const finishReason = typeof firstChoice.finish_reason === 'string' ? firstChoice.finish_reason : undefined
          const toolCalls =
            message && typeof message === 'object' && 'tool_calls' in message
              ? extractToolCalls(message.tool_calls)
              : []
          const content =
            toolCalls.length > 0
              ? extractMessageTextOnly(message)
              : extractMessageBody(message)
          pushMessage('assistant', content, toolCalls, finishReason, true)
          outputHandled = true
        }
      }
    } catch {
      // Ignore parse failure and fall back to display output extraction.
    }

    if (!outputHandled) {
      const assistantOutput = extractDisplayOutput(span.output)
      if (assistantOutput) {
        pushMessage('assistant', assistantOutput)
      }
    }
  }

  return messages
}

const roleColorMap: Record<string, string> = {
  system: '#597ef7',
  user: '#13c2c2',
  assistant: '#d48806',
  tool: '#722ed1',
  input: '#595959',
}

const roleLabelMap: Record<string, string> = {
  system: 'System',
  user: 'User',
  assistant: 'Assistant',
  tool: 'Tool',
  input: 'Input',
}

const rolePanelBgMap: Record<string, string> = {
  system: '#f0f5ff',
  user: '#e6fffb',
  assistant: '#fff7e6',
  tool: '#f9f0ff',
  input: '#fafafa',
}

const formatSpanDuration = (durationMs?: number | null) => {
  if (durationMs == null) {
    return '-'
  }
  return `${Number(durationMs.toFixed(2))}ms`
}

const formatLatencyMetric = (value?: number | null) => {
  if (value == null) {
    return '-'
  }
  return `${Number(value.toFixed(2))}ms`
}

// 统一格式化 Trace 吞吐量指标，以 tok/s 展示并保留最多 2 位小数。
const formatThroughputMetric = (value?: number | null) => {
  if (value == null) {
    return '-'
  }
  return `${Number(value.toFixed(2))} tok/s`
}

const formatTokenUsage = (inputTokens?: number, outputTokens?: number) => {
  const input = inputTokens ?? 0
  const output = outputTokens ?? 0
  const total = input + output
  return `${total}(${input}+${output})`
}

// 复制 Trace 详情里的输入输出内容；优先使用浏览器剪贴板能力，并给出统一的成功或失败提示。
const copyTraceDetailText = async (label: string, value?: string | null) => {
  if (!value) {
    message.warning(`暂无可复制的${label}`)
    return
  }
  try {
    await navigator.clipboard.writeText(value)
    message.success(`${label}已复制`)
  } catch {
    message.error(`${label}复制失败`)
  }
}

const getDisplayCreatedAt = (execution: ExecutionJob) => {
  if (!execution.created_at) {
    return execution.created_at
  }
  if (!execution.started_at) {
    return execution.created_at
  }

  const createdMs = new Date(execution.created_at).getTime()
  const startedMs = new Date(execution.started_at).getTime()
  const diffHours = (startedMs - createdMs) / (1000 * 60 * 60)

  if (diffHours > 7.5 && diffHours < 8.5) {
    return execution.started_at
  }

  return execution.created_at
}

const getOverallResultSummary = (comparisonDetail: DetailedComparisonResult) => {
  const countPassed = comparisonDetail.llm_count_check?.passed
  const outputConsistent = comparisonDetail.final_output_comparison?.consistent
  const verificationMode = comparisonDetail.final_output_comparison?.verification_mode

  if (comparisonDetail.overall_passed === true) {
    if (verificationMode === 'algorithm_short_circuit') {
      return 'LLM 调用次数检查通过，算法粗筛达到直通阈值，未再执行 LLM 语义校验。'
    }
    return 'LLM 调用次数检查通过，最终输出语义判断通过。'
  }

  if (comparisonDetail.overall_passed === false) {
    if (countPassed === false) {
      return 'LLM 调用次数检查未通过，未进入最终输出语义判断。'
    }
    if (outputConsistent === false) {
      return '最终输出语义判断未通过。'
    }
  }

  return '等待比对结果。'
}

const getOverallResultAlertType = (comparisonDetail: DetailedComparisonResult) => {
  if (comparisonDetail.overall_passed === true) {
    return 'success' as const
  }
  if (comparisonDetail.overall_passed === false) {
    return 'warning' as const
  }
  return 'info' as const
}

const STATUS_SURFACE: Record<string, { glow: string; panel: string; border: string }> = {
  queued: { glow: 'rgba(59, 130, 246, 0.16)', panel: '#eff6ff', border: '#93c5fd' },
  running: { glow: 'rgba(249, 115, 22, 0.16)', panel: '#fff7ed', border: '#fdba74' },
  pulling_trace: { glow: 'rgba(14, 165, 233, 0.16)', panel: '#ecfeff', border: '#67e8f9' },
  comparing: { glow: 'rgba(168, 85, 247, 0.16)', panel: '#faf5ff', border: '#d8b4fe' },
  completed: { glow: 'rgba(34, 197, 94, 0.16)', panel: '#f0fdf4', border: '#86efac' },
  completed_with_mismatch: { glow: 'rgba(245, 158, 11, 0.16)', panel: '#fffbeb', border: '#fcd34d' },
  failed: { glow: 'rgba(239, 68, 68, 0.14)', panel: '#fef2f2', border: '#fca5a5' },
}

const getStatusSurface = (status?: string) =>
  STATUS_SURFACE[status || ''] || {
    glow: 'rgba(148, 163, 184, 0.16)',
    panel: '#f8fafc',
    border: '#cbd5e1',
  }

// 读取列表页传入的返回地址，保证从第几页进入详情就回到第几页。
const getExecutionListReturnPath = (state: unknown) => {
  if (state && typeof state === 'object' && 'from' in state && typeof state.from === 'string') {
    return state.from
  }
  return '/executions'
}

const ExecutionDetail = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const pollRef = useRef<number | null>(null)
  const returnPath = getExecutionListReturnPath(location.state)

  const [loading, setLoading] = useState(false)
  const [traceLoading, setTraceLoading] = useState(false)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [pollTimeout, setPollTimeout] = useState(false)
  const [execution, setExecution] = useState<ExecutionJob | null>(null)
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [trace, setTrace] = useState<ExecutionTrace | null>(null)
  const [comparisonDetail, setComparisonDetail] = useState<DetailedComparisonResult | null>(null)
  const [comparisonHistory, setComparisonHistory] = useState<DetailedComparisonResult[]>([])
  const [replayHistory, setReplayHistory] = useState<ReplayTask[]>([])
  const [selectedComparisonId, setSelectedComparisonId] = useState<string>()
  const [llmModels, setLlmModels] = useState<LLMModel[]>([])
  const [selectedLlmId, setSelectedLlmId] = useState<string>()
  const [llmModalVisible, setLlmModalVisible] = useState(false)

  const llmNameMap = useMemo(
    () => Object.fromEntries(llmModels.map(model => [model.id, model.name])),
    [llmModels],
  )
  const visibleTraceSpans = useMemo(
    () =>
      trace?.spans.filter(span => span.span_type !== 'llm' || span.provider === 'openai') ?? [],
    [trace],
  )
  const getLlmModelName = (modelId?: string | null) => {
    if (!modelId) {
      return '-'
    }
    return llmNameMap[modelId] || modelId
  }
  const currentComparisonModelId = comparisonDetail?.llm_model_id || execution?.llm_model_id
  const initialComparisonModelName = getLlmModelName(execution?.llm_model_id)
  const currentComparisonModelName = getLlmModelName(currentComparisonModelId)

  const clearPolling = () => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const loadLlmModels = async () => {
    try {
      const res = await llmApi.list()
      setLlmModels(res.data || [])
    } catch (error) {
      console.error('Failed to load LLM models:', error)
    }
  }

  const loadTrace = async (executionId: string) => {
    setTraceLoading(true)
    try {
      const res = await executionApi.getTrace(executionId)
      setTrace(res.data)
    } catch (error) {
      console.error('Failed to load trace:', error)
    } finally {
      setTraceLoading(false)
    }
  }

  const loadExecution = async (executionId: string) => {
    const executionRes = await executionApi.get(executionId)
    const executionData = executionRes.data
    setExecution(executionData)
    setSelectedLlmId(executionData.llm_model_id)
    return executionData
  }

  const loadComparison = async (executionId: string, preferredComparisonId?: string) => {
    try {
      const res = await executionApi.getComparisons(executionId)
      const items = res.data || []
      setComparisonHistory(items)
      const selected =
        items.find(item => item.id === (preferredComparisonId || selectedComparisonId)) ||
        items[0] ||
        null
      setSelectedComparisonId(selected?.id)
      setComparisonDetail(selected)

      const latest = items[0]
      return !latest || !(latest.status === 'pending' || latest.status === 'processing')
    } catch (error) {
      console.error('Failed to load comparison:', error)
      return true
    }
  }

  const loadReplayHistory = async (executionId: string) => {
    try {
      const res = await executionApi.getReplays(executionId, 20, 0)
      setReplayHistory(res.data.items || [])
    } catch (error) {
      console.error('Failed to load replay history:', error)
    }
  }

  const startPolling = (executionId: string) => {
    clearPolling()
    setPollTimeout(false)
    setComparisonLoading(true)
    const startTime = Date.now()

    pollRef.current = window.setInterval(async () => {
      const done = await loadComparison(executionId)
      if (done || Date.now() - startTime > MAX_POLL_TIME) {
        clearPolling()
        setComparisonLoading(false)
        if (done) {
          try {
            await loadExecution(executionId)
          } catch (error) {
            console.error('Failed to refresh execution after comparison:', error)
          }
        }
        if (Date.now() - startTime > MAX_POLL_TIME) {
          setPollTimeout(true)
        }
      }
    }, POLL_INTERVAL)
  }

  const loadData = async () => {
    if (!id) {
      return
    }

    setLoading(true)
    try {
      const executionData = await loadExecution(id)

      if (executionData.scenario_id) {
        try {
          const scenarioRes = await scenarioApi.get(executionData.scenario_id)
          setScenario(scenarioRes.data)
        } catch (error) {
          console.error('Failed to load scenario:', error)
        }
      }

      if (
        executionData.status === 'completed' ||
        executionData.status === 'completed_with_mismatch' ||
        executionData.status === 'failed'
      ) {
        await loadTrace(id)
        await loadReplayHistory(id)
        const comparisonDone = await loadComparison(id)
        if (!comparisonDone) {
          startPolling(id)
        }
      }
    } catch (error) {
      console.error('Failed to load execution detail:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadLlmModels()
  }, [])

  useEffect(() => {
    void loadData()
    return () => {
      clearPolling()
    }
  }, [id])

  const handleSetBaseline = async () => {
    if (!id || !execution) {
      return
    }
    try {
      await scenarioApiExtended.setBaseline(execution.scenario_id, id)
      message.success('基线设置成功')
      if (execution.scenario_id) {
        const scenarioRes = await scenarioApi.get(execution.scenario_id)
        setScenario(scenarioRes.data)
      }
    } catch (error: any) {
      message.error(`基线设置失败: ${error.message}`)
    }
  }

  const handleRecompare = async () => {
    if (!id) {
      return
    }
    if (!selectedLlmId) {
      message.error('请先选择比对模型')
      return
    }

    try {
      setLlmModalVisible(false)
      await executionApi.recompare(id, selectedLlmId)
      message.success('已触发重新比对')
      setComparisonDetail(null)
      setSelectedComparisonId(undefined)
      startPolling(id)
    } catch (error: any) {
      message.error(error.message)
    }
  }

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '50px auto' }} />
  }

  if (!execution) {
    return <Result status="404" title="执行不存在" />
  }

  const duration =
    execution.started_at && execution.completed_at
      ? `${(new Date(execution.completed_at).getTime() - new Date(execution.started_at).getTime()) / 1000}s`
      : '-'
  const statusSurface = getStatusSurface(execution.status)

  return (
    <div
      style={{
        minHeight: '100%',
        padding: '8px 0 32px',
        background:
          'radial-gradient(circle at top left, rgba(14,165,233,0.10), transparent 26%), radial-gradient(circle at top right, rgba(245,158,11,0.10), transparent 22%), linear-gradient(180deg, #f4f7fb 0%, #eef3f8 100%)',
      }}
    >
      <div
        style={{
          marginBottom: 18,
          padding: '24px 28px',
          borderRadius: 28,
          background: `linear-gradient(135deg, ${statusSurface.panel} 0%, #ffffff 65%)`,
          border: `1px solid ${statusSurface.border}`,
          boxShadow: `0 24px 64px ${statusSurface.glow}`,
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 16,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'grid', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <Tag color={STATUS_COLORS[execution.status] || 'default'} style={{ marginInlineEnd: 0, borderRadius: 999, paddingInline: 12 }}>
                {STATUS_TEXT[execution.status] || execution.status}
              </Tag>
              {execution.comparison_passed === true ? (
                <Tag color="green" style={{ marginInlineEnd: 0, borderRadius: 999, paddingInline: 12 }}>
                  比对通过
                </Tag>
              ) : execution.comparison_passed === false ? (
                <Tag color="red" style={{ marginInlineEnd: 0, borderRadius: 999, paddingInline: 12 }}>
                  比对未通过
                </Tag>
              ) : null}
            </div>
            <div style={{ fontSize: 30, fontWeight: 800, color: '#0f172a', letterSpacing: '-0.02em' }}>执行详情</div>
            <div style={{ color: '#475569', maxWidth: 860, lineHeight: 1.7 }}>
              查看执行状态、比对结论，以及仅保留 OpenAI LLM spans 的 Trace 回放详情。
            </div>
          </div>
          <Button
            type="primary"
            ghost
            icon={<LeftOutlined />}
            onClick={() => navigate(returnPath)}
            style={{ borderRadius: 999, height: 40, paddingInline: 18 }}
          >
            返回列表
          </Button>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 14,
            marginTop: 22,
          }}
        >
          {[
            { label: '场景', value: scenario?.name || execution.scenario_id },
            { label: '首次比对模型', value: initialComparisonModelName },
            { label: '当前比对模型', value: currentComparisonModelName },
            { label: '执行耗时', value: duration },
            { label: 'Trace ID', value: execution.trace_id || '-' },
          ].map(item => (
            <div
              key={item.label}
              style={{
                padding: '16px 18px',
                borderRadius: 20,
                background: 'rgba(255,255,255,0.74)',
                border: '1px solid rgba(255,255,255,0.9)',
                boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.7)',
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 700, color: '#64748b', marginBottom: 8 }}>{item.label}</div>
              <div style={{ color: '#0f172a', fontSize: 15, fontWeight: 700, wordBreak: 'break-word' }}>{item.value}</div>
            </div>
          ))}
        </div>
      </div>

      <Card
        title="执行详情"
        style={{
          borderRadius: 24,
          border: '1px solid rgba(226,232,240,0.95)',
          boxShadow: '0 20px 45px rgba(15, 23, 42, 0.06)',
          overflow: 'hidden',
          background: 'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(248,250,252,0.98) 100%)',
        }}
        styles={{
          header: { background: 'transparent', borderBottom: '1px solid #eef2f7', paddingInline: 24 },
          body: { padding: 24 },
        }}
      >
        <Descriptions bordered column={2}>
          <Descriptions.Item label="执行 ID">{execution.id}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={STATUS_COLORS[execution.status] || 'default'}>{STATUS_TEXT[execution.status] || execution.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="测试场景">{scenario?.name || execution.scenario_id}</Descriptions.Item>
          <Descriptions.Item label="首次比对模型">{initialComparisonModelName}</Descriptions.Item>
          <Descriptions.Item label="当前比对模型">{currentComparisonModelName}</Descriptions.Item>
          <Descriptions.Item label="本次 Session">{execution.user_session || '-'}</Descriptions.Item>
          <Descriptions.Item label="Trace ID">{execution.trace_id || '-'}</Descriptions.Item>
          <Descriptions.Item label="比对结果">
            {execution.comparison_passed === true ? (
              <Tag color="green">通过</Tag>
            ) : execution.comparison_passed === false ? (
              <Tag color="red">未通过</Tag>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="LLM 调用范围">
            {scenario ? `${scenario.llm_count_min} ~ ${scenario.llm_count_max}` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="执行耗时">{duration}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{formatLocalTime(getDisplayCreatedAt(execution))}</Descriptions.Item>
          <Descriptions.Item label="完成时间">{formatLocalTime(execution.completed_at)}</Descriptions.Item>
        </Descriptions>

        {execution.status === 'failed' && execution.error_message && (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 16 }}
            message="执行错误"
            description={execution.error_message}
          />
        )}
      </Card>

      <Card
        title="比对详情"
        style={{
          marginTop: 18,
          borderRadius: 24,
          border: '1px solid rgba(226,232,240,0.95)',
          boxShadow: '0 20px 45px rgba(15, 23, 42, 0.06)',
          overflow: 'hidden',
          background: 'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(247,250,252,0.98) 100%)',
        }}
        styles={{
          header: { background: 'transparent', borderBottom: '1px solid #eef2f7', paddingInline: 24 },
          body: { padding: 24 },
        }}
        extra={
          <Space>
            <Button icon={<PushpinOutlined />} onClick={() => void handleSetBaseline()}>
              设为基线
            </Button>
            <Button
              icon={<ReloadOutlined />}
              loading={comparisonLoading}
              onClick={() => {
                setSelectedLlmId(currentComparisonModelId || execution.llm_model_id)
                setLlmModalVisible(true)
              }}
            >
              重新比对
            </Button>
          </Space>
        }
      >
        {pollTimeout && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="轮询超时"
            description="比对可能仍在进行中，请稍后刷新页面。"
          />
        )}

        {comparisonLoading && (
          <div style={{ textAlign: 'center', padding: 24 }}>
            <Spin />
            <div style={{ marginTop: 12 }}>比对进行中...</div>
          </div>
        )}

        {!comparisonLoading && !comparisonDetail && (
          <Alert
            type="info"
            showIcon
            message="暂无比对结果"
            description="当前执行还没有可展示的比对结果。"
          />
        )}

        {!comparisonLoading && comparisonDetail && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '280px minmax(0, 1fr)',
              gap: 16,
              alignItems: 'start',
            }}
          >
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
                padding: 10,
                borderRadius: 18,
                background: 'linear-gradient(180deg, #f8fafc 0%, #edf4ff 100%)',
                border: '1px solid #dbeafe',
                alignSelf: 'start',
                height: 'min(720px, calc(100vh - 180px))',
                minHeight: 520,
                position: 'sticky',
                top: 12,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontWeight: 800, color: '#0f172a' }}>比对历史</div>
                <Tag color="blue" style={{ marginInlineEnd: 0 }}>{comparisonHistory.length} 次</Tag>
              </div>
              <div
                style={{
                  display: 'grid',
                  alignContent: 'start',
                  gap: 10,
                  flex: 1,
                  minHeight: 0,
                  overflowY: 'auto',
                  paddingRight: 2,
                }}
              >
                {comparisonHistory.map((item, index) => {
                  const isSelected = item.id === comparisonDetail.id
                  const count = item.llm_count_check
                  const final = item.final_output_comparison
                  const modelName = getLlmModelName(item.llm_model_id || execution.llm_model_id)
                  const statusColor =
                    item.status === 'processing' || item.status === 'pending'
                      ? '#2563eb'
                      : item.overall_passed === true
                        ? '#16a34a'
                        : item.status === 'failed'
                          ? '#dc2626'
                          : '#d97706'

                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        setSelectedComparisonId(item.id)
                        setComparisonDetail(item)
                      }}
                      style={{
                        width: '100%',
                        textAlign: 'left',
                        cursor: 'pointer',
                        borderRadius: 12,
                        border: isSelected ? '1px solid #2563eb' : '1px solid #e5e7eb',
                        background: isSelected ? '#eff6ff' : '#ffffff',
                        boxShadow: isSelected
                          ? '0 10px 22px rgba(37, 99, 235, 0.12)'
                          : '0 4px 14px rgba(15, 23, 42, 0.04)',
                        padding: 10,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
                        <span style={{ fontWeight: 800, color: '#0f172a' }}>
                          {index === 0 ? '最新比对' : `历史比对 ${comparisonHistory.length - index}`}
                        </span>
                        <Tag
                          color={item.overall_passed === true ? 'green' : item.status === 'failed' ? 'red' : 'orange'}
                          style={{ marginInlineEnd: 0 }}
                        >
                          {item.status === 'processing' || item.status === 'pending'
                            ? '处理中'
                            : item.status === 'failed'
                              ? '失败'
                              : item.overall_passed === true
                                ? '通过'
                                : '未通过'}
                        </Tag>
                      </div>
                      <div style={{ display: 'grid', gap: 4, color: '#475569', fontSize: 12 }}>
                        <div>
                          <span style={{ color: '#64748b' }}>模型：</span>
                          <span style={{ color: '#0f172a', fontWeight: 700 }}>{modelName}</span>
                        </div>
                        <div>
                          <span style={{ color: '#64748b' }}>时间：</span>
                          {formatLocalTime(item.completed_at || item.created_at)}
                        </div>
                        {count && (
                          <div>
                            <span style={{ color: '#64748b' }}>LLM 次数：</span>
                            <span style={{ color: count.passed ? '#16a34a' : '#dc2626', fontWeight: 700 }}>
                              {count.actual_count} / {count.expected_min}-{count.expected_max}
                            </span>
                          </div>
                        )}
                        {final?.algorithm_similarity != null && (
                          <div>
                            <span style={{ color: '#64748b' }}>算法粗筛：</span>
                            {final.algorithm_similarity.toFixed(3)}
                          </div>
                        )}
                      </div>
                      <div style={{ marginTop: 8, height: 3, borderRadius: 999, background: statusColor }} />
                    </button>
                  )
                })}
              </div>
            </div>

            <Space direction="vertical" size={16} style={{ width: '100%', minWidth: 0, overflow: 'hidden' }}>
            {comparisonDetail.status === 'failed' && (
              <Alert
                type="error"
                showIcon
                message="比对失败"
                description={comparisonDetail.error_message || '未知错误'}
              />
            )}

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                gap: 14,
              }}
            >
              <div
                style={{
                  padding: '18px 20px',
                  borderRadius: 20,
                  background:
                    comparisonDetail.overall_passed === true
                      ? 'linear-gradient(135deg, #ecfdf5 0%, #ffffff 100%)'
                      : comparisonDetail.overall_passed === false
                        ? 'linear-gradient(135deg, #fef2f2 0%, #ffffff 100%)'
                        : 'linear-gradient(135deg, #f8fafc 0%, #ffffff 100%)',
                  border:
                    comparisonDetail.overall_passed === true
                      ? '1px solid #86efac'
                      : comparisonDetail.overall_passed === false
                        ? '1px solid #fca5a5'
                        : '1px solid #e2e8f0',
                }}
              >
                <Statistic
                  title="总体结果"
                  value={
                    comparisonDetail.overall_passed === true
                      ? '通过'
                      : comparisonDetail.overall_passed === false
                        ? '未通过'
                        : '未判定'
                  }
                  valueStyle={{
                    color:
                      comparisonDetail.overall_passed === true
                        ? '#15803d'
                        : comparisonDetail.overall_passed === false
                          ? '#b91c1c'
                          : '#475569',
                    fontWeight: 800,
                  }}
                />
              </div>
              <div
                style={{
                  padding: '18px 20px',
                  borderRadius: 20,
                  background: 'linear-gradient(135deg, #f8fafc 0%, #ffffff 100%)',
                  border: '1px solid #e2e8f0',
                }}
              >
                <div style={{ fontSize: 13, color: '#64748b', marginBottom: 8 }}>当前比对模型</div>
                <div style={{ color: '#0f172a', fontWeight: 800, fontSize: 20, wordBreak: 'break-word' }}>
                  {getLlmModelName(comparisonDetail.llm_model_id || execution.llm_model_id)}
                </div>
              </div>
              {comparisonDetail.llm_count_check && (
                <div
                  style={{
                    padding: '18px 20px',
                    borderRadius: 20,
                    background: 'linear-gradient(135deg, #eff6ff 0%, #ffffff 100%)',
                    border: '1px solid #bfdbfe',
                  }}
                >
                  <Statistic
                    title="实际 LLM 调用次数"
                    value={comparisonDetail.llm_count_check.actual_count}
                    suffix={`/ ${comparisonDetail.llm_count_check.expected_min}-${comparisonDetail.llm_count_check.expected_max}`}
                    valueStyle={{ color: '#1d4ed8', fontWeight: 800 }}
                  />
                </div>
              )}
            </div>

            <Alert
              showIcon
              type={getOverallResultAlertType(comparisonDetail)}
              message="结果说明"
              description={getOverallResultSummary(comparisonDetail)}
            />

            {comparisonDetail.llm_count_check ? (
              <Descriptions bordered size="small" column={2} title="LLM 调用次数检查">
                <Descriptions.Item label="期望范围">
                  {comparisonDetail.llm_count_check.expected_min} ~ {comparisonDetail.llm_count_check.expected_max}
                </Descriptions.Item>
                <Descriptions.Item label="实际次数">
                  {comparisonDetail.llm_count_check.actual_count}
                </Descriptions.Item>
                <Descriptions.Item label="检查结果" span={2}>
                  <Tag color={comparisonDetail.llm_count_check.passed ? 'green' : 'red'}>
                    {comparisonDetail.llm_count_check.passed ? '通过' : '未通过'}
                  </Tag>
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Alert type="info" showIcon message="暂无 LLM 调用次数检查结果" />
            )}

            {comparisonDetail.final_output_comparison ? (
              <Descriptions bordered size="small" column={1} title="最终输出比对">
                <Descriptions.Item label="比对结果">
                  <Tag color={comparisonDetail.final_output_comparison.consistent ? 'green' : 'red'}>
                    {comparisonDetail.final_output_comparison.consistent ? '一致' : '不一致'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="判断原因">
                  {formatComparisonReason(comparisonDetail.final_output_comparison.reason)}
                </Descriptions.Item>
                <Descriptions.Item label="算法粗筛相似度">
                  {comparisonDetail.final_output_comparison.algorithm_similarity != null
                    ? comparisonDetail.final_output_comparison.algorithm_similarity.toFixed(3)
                    : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="判定方式">
                  {formatVerificationMode(comparisonDetail.final_output_comparison.verification_mode)}
                </Descriptions.Item>
                <Descriptions.Item label="基线输出">
                  <pre
                    style={{
                      margin: 0,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      maxHeight: 220,
                      overflow: 'auto',
                    }}
                  >
                    {extractDisplayOutput(comparisonDetail.final_output_comparison.baseline_output) || '-'}
                  </pre>
                </Descriptions.Item>
                <Descriptions.Item label="实际输出">
                  <pre
                    style={{
                      margin: 0,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      maxHeight: 220,
                      overflow: 'auto',
                    }}
                  >
                    {extractDisplayOutput(comparisonDetail.final_output_comparison.actual_output) || '-'}
                  </pre>
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Alert type="info" showIcon message="暂无最终输出比对结果" />
            )}
            </Space>
          </div>
        )}
      </Card>

      <Card
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span>回放历史</span>
            <Tag color="blue" style={{ marginInlineEnd: 0, borderRadius: 999, paddingInline: 10 }}>
              {replayHistory.length} 次
            </Tag>
          </div>
        }
        style={{
          marginTop: 18,
          borderRadius: 24,
          border: '1px solid rgba(226,232,240,0.95)',
          boxShadow: '0 20px 45px rgba(15, 23, 42, 0.06)',
        }}
      >
        {replayHistory.length === 0 ? (
          <Alert type="info" showIcon message="暂无链路回放记录" />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
            {replayHistory.map(item => (
              <button
                key={item.id}
                type="button"
                onClick={() => navigate(`/replays/${item.id}`)}
                style={{
                  textAlign: 'left',
                  border: '1px solid #dbeafe',
                  borderRadius: 16,
                  padding: 14,
                  cursor: 'pointer',
                  background: '#f8fbff',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <strong>{item.baseline_source === 'reference_execution' ? '当前执行比较' : '场景基线比较'}</strong>
                  <Tag color={item.overall_passed ? 'green' : item.overall_passed === false ? 'red' : 'blue'}>
                    {item.overall_passed ? '通过' : item.overall_passed === false ? '未通过' : STATUS_TEXT[item.status] || item.status}
                  </Tag>
                </div>
                <div style={{ color: '#64748b', fontSize: 12 }}>时间：{formatLocalTime(item.created_at)}</div>
                <div style={{ color: '#64748b', fontSize: 12, marginTop: 4, wordBreak: 'break-all' }}>
                  回放执行：{item.replay_execution_id}
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>

      <Card
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span>Trace 回放</span>
            <Tag color="blue" style={{ marginInlineEnd: 0, borderRadius: 999, paddingInline: 10 }}>
              {visibleTraceSpans.length} spans
            </Tag>
            <Tag color="geekblue" style={{ marginInlineEnd: 0, borderRadius: 999, paddingInline: 10 }}>
              平均 TTFT {formatLatencyMetric(trace?.avg_ttft_ms)}
            </Tag>
            <Tag color="blue" style={{ marginInlineEnd: 0, borderRadius: 999, paddingInline: 10 }}>
              总耗时 {formatLatencyMetric(trace?.total_duration_ms)}
            </Tag>
            <Tag color="purple" style={{ marginInlineEnd: 0, borderRadius: 999, paddingInline: 10 }}>
              加权平均 TPOT {formatLatencyMetric(trace?.avg_tpot_ms)}
            </Tag>
            <Tag color="volcano" style={{ marginInlineEnd: 0, borderRadius: 999, paddingInline: 10 }}>
              总吞吐量 {formatThroughputMetric(trace?.total_throughput_tps)}
            </Tag>
            <Tag color="cyan" style={{ marginInlineEnd: 0, borderRadius: 999, paddingInline: 10 }}>
              输出吞吐量 {formatThroughputMetric(trace?.output_throughput_tps)}
            </Tag>
            <Tag color="gold" style={{ marginInlineEnd: 0, borderRadius: 999, paddingInline: 10 }}>
              总 Tokens: {formatTokenUsage(trace?.total_input_tokens, trace?.total_output_tokens)}
            </Tag>
          </div>
        }
        style={{
          marginTop: 18,
          borderRadius: 24,
          border: '1px solid rgba(226,232,240,0.95)',
          boxShadow: '0 20px 45px rgba(15, 23, 42, 0.06)',
          overflow: 'hidden',
          background: 'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(244,247,251,0.98) 100%)',
        }}
        styles={{
          header: { background: 'transparent', borderBottom: '1px solid #eef2f7', paddingInline: 24 },
          body: { background: 'linear-gradient(180deg, #f8fbff 0%, #f5f7fb 100%)', padding: 24 },
        }}
      >
        {traceLoading && <Spin />}

        {!traceLoading && visibleTraceSpans.length > 0 && (
          <Collapse
            ghost
            style={{
              background: 'transparent',
            }}
            items={visibleTraceSpans.map(span => ({
              key: span.span_id,
              label: (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      padding: '12px 14px',
                      borderRadius: 14,
                      background: getSpanTheme(span.span_type).headerBg,
                      border: `1px solid ${getSpanTheme(span.span_type).borderColor}`,
                      boxShadow: '0 6px 18px rgba(15, 23, 42, 0.04)',
                    }}
                  >
                    <div
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: 999,
                        background:
                          span.span_type === 'llm'
                            ? '#1677ff'
                            : span.span_type === 'tool'
                              ? '#fa541c'
                              : '#8c8c8c',
                        flex: '0 0 auto',
                      }}
                    />
                    <Tag color={getSpanTheme(span.span_type).tagColor} style={{ marginInlineEnd: 0 }}>
                      {span.span_type.toUpperCase()}
                    </Tag>
                    <div style={{ display: 'grid', gap: 2, minWidth: 0, flex: 1 }}>
                      <div
                        style={{
                          fontWeight: 700,
                          color: '#1f1f1f',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {span.name}
                      </div>
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', color: '#666', fontSize: 12 }}>
                        <span>耗时 {formatSpanDuration(span.duration_ms)}</span>
                        {span.span_type === 'llm' && (
                          <span>Tokens: {formatTokenUsage(span.input_tokens, span.output_tokens)}</span>
                        )}
                        {span.ttft_ms != null && <span>TTFT {formatLatencyMetric(span.ttft_ms)}</span>}
                        {span.tpot_ms != null && <span>TPOT {formatLatencyMetric(span.tpot_ms)}</span>}
                        {span.output_throughput_tps != null && (
                          <span>输出吞吐量 {formatThroughputMetric(span.output_throughput_tps)}</span>
                        )}
                        {span.total_throughput_tps != null && (
                          <span>总吞吐量 {formatThroughputMetric(span.total_throughput_tps)}</span>
                        )}
                      </div>
                    </div>
                  </div>
                ),
              children: (
                <div
                  style={{
                    background: '#fff',
                    border: `1px solid ${getSpanTheme(span.span_type).borderColor}`,
                    borderRadius: 16,
                    padding: 16,
                    boxShadow: '0 8px 24px rgba(15, 23, 42, 0.04)',
                  }}
                >
                  {span.span_type === 'llm' ? (
                    <Tabs
                      defaultActiveKey="messages"
                      items={[
                        {
                          key: 'messages',
                          label: 'Messages',
                          children: (
                            <div style={{ display: 'grid', gap: 12 }}>
                              {extractLLMMessages(span).length > 0 ? (
                                <Collapse
                                  ghost
                                  items={extractLLMMessages(span).map((messageItem, index) => ({
                                    key: `${span.span_id}-message-${index}`,
                                    label: (
                                      <span
                                        style={{
                                          fontWeight: 700,
                                          color: roleColorMap[messageItem.role] || '#595959',
                                        }}
                                      >
                                        {roleLabelMap[messageItem.role] || messageItem.role}
                                      </span>
                                    ),
                                    children: (
                                      <div style={{ display: 'grid', gap: 10 }}>
                                        {messageItem.content ? (
                                          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                            {messageItem.content}
                                          </pre>
                                        ) : !messageItem.toolCalls?.length ? (
                                          <div
                                            style={{
                                              color: '#8c8c8c',
                                              fontStyle: 'italic',
                                            }}
                                          >
                                            空响应
                                          </div>
                                        ) : null}
                                        {messageItem.finishReason && (
                                          <div style={{ color: '#64748b', fontSize: 13 }}>
                                            Finish reason: {messageItem.finishReason}
                                          </div>
                                        )}
                                        {messageItem.toolCalls?.map((toolCall, toolIndex) => (
                                          <div
                                            key={`${span.span_id}-message-${index}-tool-${toolIndex}`}
                                            style={{
                                              border: '1px solid #dbeafe',
                                              borderRadius: 10,
                                              overflow: 'hidden',
                                              background: '#f8fbff',
                                            }}
                                          >
                                            <div
                                              style={{
                                                padding: '8px 12px',
                                                background: '#eff6ff',
                                                borderBottom: '1px solid #dbeafe',
                                                color: '#1d4ed8',
                                                fontWeight: 700,
                                                fontSize: 13,
                                              }}
                                            >
                                              {toolCall.name}
                                            </div>
                                            {toolCall.content && (
                                              <pre
                                                style={{
                                                  margin: 0,
                                                  padding: '10px 12px',
                                                  whiteSpace: 'pre-wrap',
                                                  wordBreak: 'break-word',
                                                  color: '#0f172a',
                                                  background: '#ffffff',
                                                }}
                                              >
                                                {toolCall.content}
                                              </pre>
                                            )}
                                          </div>
                                        ))}
                                      </div>
                                    ),
                                    style: {
                                      border: '1px solid #edf2f7',
                                      borderLeft: `4px solid ${roleColorMap[messageItem.role] || '#d9d9d9'}`,
                                      borderRadius: 12,
                                      background: rolePanelBgMap[messageItem.role] || '#fff',
                                      marginBottom: 10,
                                    },
                                  }))}
                                />
                              ) : (
                                <Alert type="info" showIcon message="暂无可提取的 LLM messages" />
                              )}
                            </div>
                          ),
                        },
                        {
                          key: 'details',
                          label: 'Details',
                          children: (
                            <Descriptions
                              bordered
                              size="small"
                              column={1}
                              styles={{
                                label: { width: 88, fontWeight: 600 },
                                content: { background: '#fcfcfd' },
                              }}
                            >
                              <Descriptions.Item label="Tokens">
                                {formatTokenUsage(span.input_tokens, span.output_tokens)}
                              </Descriptions.Item>
                              <Descriptions.Item label="输入">
                                <div style={{ display: 'grid', gap: 8 }}>
                                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                                    <Button
                                      size="small"
                                      type="text"
                                      icon={<CopyOutlined />}
                                      onClick={() => void copyTraceDetailText('输入', stringifyPretty(span.input))}
                                    >
                                      复制
                                    </Button>
                                  </div>
                                  <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                    {stringifyPretty(span.input)}
                                  </pre>
                                </div>
                              </Descriptions.Item>
                              <Descriptions.Item label="输出">
                                <div style={{ display: 'grid', gap: 8 }}>
                                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                                    <Button
                                      size="small"
                                      type="text"
                                      icon={<CopyOutlined />}
                                      onClick={() => void copyTraceDetailText('输出', stringifyPretty(span.output))}
                                    >
                                      复制
                                    </Button>
                                  </div>
                                  <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                    {stringifyPretty(span.output)}
                                  </pre>
                                </div>
                              </Descriptions.Item>
                            </Descriptions>
                          ),
                        },
                      ]}
                    />
                  ) : (
                    <div style={{ display: 'grid', gap: 14 }}>
                      {span.input && (
                        <div
                          style={{
                            border: '1px solid #f0f0f0',
                            borderRadius: 12,
                            padding: 14,
                            background: '#fffaf7',
                          }}
                        >
                          <div style={{ fontWeight: 700, marginBottom: 8, color: '#8c2f00' }}>输入</div>
                          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                            {stringifyPretty(span.input)}
                          </pre>
                        </div>
                      )}
                      {span.output && (
                        <div
                          style={{
                            border: '1px solid #f0f0f0',
                            borderRadius: 12,
                            padding: 14,
                            background: '#fff',
                          }}
                        >
                          <div style={{ fontWeight: 700, marginBottom: 8, color: '#8c2f00' }}>输出</div>
                          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                            {stringifyPretty(span.output)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ),
            }))}
          />
        )}

        {!traceLoading && visibleTraceSpans.length === 0 && (
          <Alert type="info" showIcon message="暂无 Trace 数据" />
        )}
      </Card>

      <Modal
        title="选择比对模型"
        open={llmModalVisible}
        onCancel={() => setLlmModalVisible(false)}
        onOk={() => void handleRecompare()}
        okText="开始比对"
        cancelText="取消"
      >
        <p style={{ marginBottom: 12 }}>重新比对必须选择一个 LLM 模型。</p>
        <Select
          style={{ width: '100%' }}
          placeholder="选择比对模型"
          value={selectedLlmId}
          onChange={value => setSelectedLlmId(value)}
          options={llmModels.map(model => ({ label: model.name, value: model.id }))}
        />
      </Modal>
    </div>
  )
}

export default ExecutionDetail
