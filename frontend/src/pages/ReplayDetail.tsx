import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert, Button, Card, Collapse, Descriptions, Select, Space, Spin, Statistic, Tag, Tabs, message } from 'antd'
import { LeftOutlined, ReloadOutlined } from '@ant-design/icons'

import { executionApi, llmApi, replayApi } from '../api/client'
import type { ExecutionTrace, LLMModel, ReplayDetail as ReplayDetailType } from '../api/types'

const POLL_INTERVAL = 2000
const MAX_POLL_TIME = 5 * 60 * 1000

const STATUS_TEXT: Record<string, string> = {
  queued: '排队中',
  running: '执行中',
  pulling_trace: '拉取 Trace',
  comparing: '结果比对',
  completed: '完成',
  failed: '失败',
}

const STATUS_COLOR: Record<string, string> = {
  queued: 'blue',
  running: 'orange',
  pulling_trace: 'cyan',
  comparing: 'purple',
  completed: 'green',
  failed: 'red',
}

const BASELINE_TEXT: Record<string, string> = {
  scenario_baseline: '场景基线',
  reference_execution: '当前执行',
}

const formatLocalTime = (value?: string | null) => {
  if (!value) return '-'
  const isoLikeValue = value.includes('T') ? value : value.replace(' ', 'T')
  const normalizedValue = /(?:Z|[+-]\d{2}:\d{2})$/.test(isoLikeValue) ? isoLikeValue : `${isoLikeValue}Z`
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(normalizedValue))
}

const pretty = (value?: string | null) => {
  if (!value) return '-'
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

const formatDuration = (durationMs?: number | null) => {
  if (durationMs == null) return '-'
  return durationMs >= 1000 ? `${(durationMs / 1000).toFixed(1)}s` : `${durationMs}ms`
}

const tokenUsage = (input?: number, output?: number) => `${(input || 0) + (output || 0)}(${input || 0}+${output || 0})`

const visibleSpans = (trace?: ExecutionTrace | null) =>
  trace?.spans.filter(span => span.span_type !== 'llm' || span.provider === 'openai') ?? []

const parseSnapshot = (value?: string) => {
  if (!value) return {}
  try {
    return JSON.parse(value) as Record<string, unknown>
  } catch {
    return {}
  }
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
  if (spanType === 'llm') return SPAN_THEME.llm
  if (spanType === 'tool') return SPAN_THEME.tool
  return SPAN_THEME.default
}

const stringifyPretty = (value?: string | null) => pretty(value)

const extractTextContent = (content: unknown): string => {
  if (typeof content === 'string') return content

  if (Array.isArray(content)) {
    const textParts = content
      .map(item => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'type' in item && item.type === 'text' && 'text' in item) {
          return typeof item.text === 'string' ? item.text : ''
        }
        return ''
      })
      .filter(Boolean)

    if (textParts.length > 0) return textParts.join('\n')
  }

  return ''
}

const extractToolCallSummary = (value: unknown): string => {
  if (!Array.isArray(value) || value.length === 0) return ''

  const summaries = value
    .map(call => {
      if (!call || typeof call !== 'object') return ''

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

      if (!rawArguments) return functionName ? `工具调用: ${functionName}` : ''

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
  if (!Array.isArray(value) || value.length === 0) return []

  return value
    .map(call => {
      if (!call || typeof call !== 'object') return null

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

      if (!rawArguments) return { name, content: '' }

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
  if (!message || typeof message !== 'object') return fallback || ''

  const textContent = 'content' in message ? extractTextContent(message.content) : ''
  if (textContent) return textContent

  const toolCallSummary = 'tool_calls' in message ? extractToolCallSummary(message.tool_calls) : ''
  if (toolCallSummary) return toolCallSummary

  return fallback || ''
}

const extractMessageTextOnly = (message: unknown, fallback?: string) => {
  if (!message || typeof message !== 'object') return fallback || ''

  const textContent = 'content' in message ? extractTextContent(message.content) : ''
  return textContent || fallback || ''
}

const extractDisplayOutput = (output?: string) => {
  if (!output) return ''

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
      if (typeof content === 'string') return content
      return JSON.stringify(content, null, 2)
    }

    if (Array.isArray(parsed?.assistantTexts)) return parsed.assistantTexts.join('\n')

    if (Array.isArray(parsed?.choices) && parsed.choices.length > 0) {
      const firstChoice = parsed.choices[0]
      if (firstChoice?.message) {
        const message = firstChoice.message
        const textContent = extractTextContent(message.content)
        if (textContent) return textContent
        const toolCallSummary = extractToolCallSummary(message.tool_calls)
        if (toolCallSummary) return toolCallSummary
      }
    }
  } catch {
    return output
  }

  return output
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
    if (!text && calls.length === 0 && !showWhenEmpty) return
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
        if (typeof parsed.systemPrompt === 'string') pushMessage('system', parsed.systemPrompt)
        if (typeof parsed.prompt === 'string') pushMessage('user', parsed.prompt)
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
            message && typeof message === 'object' && 'tool_calls' in message ? extractToolCalls(message.tool_calls) : []
          const content = toolCalls.length > 0 ? extractMessageTextOnly(message) : extractMessageBody(message)
          pushMessage('assistant', content, toolCalls, finishReason, true)
          outputHandled = true
        }
      }
    } catch {
      // Ignore parse failure and fall back to display output extraction.
    }

    if (!outputHandled) {
      const assistantOutput = extractDisplayOutput(span.output)
      if (assistantOutput) pushMessage('assistant', assistantOutput)
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

const TracePanel = ({ title, trace, loading }: { title: string; trace: ExecutionTrace | null; loading: boolean }) => {
  const spans = visibleSpans(trace)

  return (
    <Card
      title={`${title} · ${spans.length} spans`}
      style={{
        borderRadius: 24,
        minHeight: 320,
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
      {loading && <Spin />}
      {!loading && spans.length === 0 && <Alert type="info" showIcon message="暂无 Trace 数据" />}
      {!loading && spans.length > 0 && (
        <Collapse
          ghost
          style={{ background: 'transparent' }}
          items={spans.map(span => ({
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
                        span.span_type === 'llm' ? '#1677ff' : span.span_type === 'tool' ? '#fa541c' : '#8c8c8c',
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
                      <span>耗时 {formatDuration(span.duration_ms)}</span>
                      {span.span_type === 'llm' && <span>Tokens: {tokenUsage(span.input_tokens, span.output_tokens)}</span>}
                      {span.ttft_ms != null && <span>TTFT {Math.round(span.ttft_ms)}ms</span>}
                      {span.tpot_ms != null && <span>TPOT {span.tpot_ms.toFixed(1)}ms</span>}
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
                              {tokenUsage(span.input_tokens, span.output_tokens)}
                            </Descriptions.Item>
                            <Descriptions.Item label="输入">
                              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                {stringifyPretty(span.input)}
                              </pre>
                            </Descriptions.Item>
                            <Descriptions.Item label="输出">
                              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                {stringifyPretty(span.output)}
                              </pre>
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
    </Card>
  )
}

const ReplayDetail = () => {
  const { replayTaskId } = useParams<{ replayTaskId: string }>()
  const navigate = useNavigate()
  const pollRef = useRef<number | null>(null)

  const [detail, setDetail] = useState<ReplayDetailType | null>(null)
  const [loading, setLoading] = useState(false)
  const [originalTrace, setOriginalTrace] = useState<ExecutionTrace | null>(null)
  const [replayTrace, setReplayTrace] = useState<ExecutionTrace | null>(null)
  const [traceLoading, setTraceLoading] = useState(false)
  const [llmModels, setLlmModels] = useState<LLMModel[]>([])
  const [selectedLlmId, setSelectedLlmId] = useState<string>()

  const snapshot = useMemo(() => parseSnapshot(detail?.replay_task.baseline_snapshot_json), [detail])
  const llmNameMap = useMemo(() => Object.fromEntries(llmModels.map(model => [model.id, model.name])), [llmModels])
  const isReference = detail?.replay_task.baseline_source === 'reference_execution'
  const isRunning = ['queued', 'running', 'pulling_trace', 'comparing'].includes(detail?.replay_task.status || '')

  const clearPolling = () => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const loadTraceData = async (nextDetail: ReplayDetailType) => {
    if (!['completed', 'failed'].includes(nextDetail.replay_task.status)) return
    setTraceLoading(true)
    try {
      const requests = [executionApi.getTrace(nextDetail.replay_execution.id)]
      if (nextDetail.replay_task.baseline_source === 'reference_execution') {
        requests.unshift(executionApi.getTrace(nextDetail.original_execution.id))
      }
      const responses = await Promise.all(requests)
      if (nextDetail.replay_task.baseline_source === 'reference_execution') {
        setOriginalTrace(responses[0].data)
        setReplayTrace(responses[1].data)
      } else {
        setOriginalTrace(null)
        setReplayTrace(responses[0].data)
      }
    } catch (error: any) {
      message.error(error.message)
    } finally {
      setTraceLoading(false)
    }
  }

  const loadDetail = async () => {
    if (!replayTaskId) return null
    const res = await replayApi.get(replayTaskId)
    setDetail(res.data)
    setSelectedLlmId(res.data.replay_task.llm_model_id)
    return res.data
  }

  const startPolling = () => {
    clearPolling()
    const startedAt = Date.now()
    pollRef.current = window.setInterval(async () => {
      try {
        const nextDetail = await loadDetail()
        if (!nextDetail) return
        if (!['queued', 'running', 'pulling_trace', 'comparing'].includes(nextDetail.replay_task.status)) {
          clearPolling()
          await loadTraceData(nextDetail)
        }
        if (Date.now() - startedAt > MAX_POLL_TIME) {
          clearPolling()
          message.info('回放仍在后台执行，可稍后刷新查看')
        }
      } catch (error: any) {
        clearPolling()
        message.error(error.message)
      }
    }, POLL_INTERVAL)
  }

  const loadAll = async () => {
    setLoading(true)
    try {
      const [nextDetail, llmRes] = await Promise.all([loadDetail(), llmApi.list()])
      setLlmModels(llmRes.data || [])
      if (nextDetail) {
        await loadTraceData(nextDetail)
        if (['queued', 'running', 'pulling_trace', 'comparing'].includes(nextDetail.replay_task.status)) {
          startPolling()
        }
      }
    } catch (error: any) {
      message.error(error.message)
    } finally {
      setLoading(false)
    }
  }

  const handleRecompare = async () => {
    if (!detail || !selectedLlmId) return
    try {
      await replayApi.recompare(detail.replay_task.id, selectedLlmId)
      message.success('已触发回放重新比对')
      startPolling()
    } catch (error: any) {
      message.error(error.message)
    }
  }

  useEffect(() => {
    void loadAll()
    return clearPolling
  }, [replayTaskId])

  if (loading && !detail) {
    return <Spin />
  }

  if (!detail) {
    return <Alert type="error" showIcon message="回放任务不存在" />
  }

  const comparison = detail.comparison
  const baselineOutput = String(snapshot.baseline_output || '')

  return (
    <div style={{ display: 'grid', gap: 18 }}>
      <Button icon={<LeftOutlined />} onClick={() => navigate(`/execution/${detail.original_execution.id}`)} style={{ width: 120 }}>
        返回执行
      </Button>

      <Card style={{ borderRadius: 24, background: 'linear-gradient(135deg, #eef6ff 0%, #ffffff 58%, #f8fafc 100%)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1fr 1fr', gap: 16 }}>
          <Statistic title="回放状态" value={STATUS_TEXT[detail.replay_task.status] || detail.replay_task.status} />
          <Statistic title="比较基准" value={BASELINE_TEXT[detail.replay_task.baseline_source] || detail.replay_task.baseline_source} />
          <Statistic
            title="回放结果"
            value={detail.replay_task.overall_passed === true ? '通过' : detail.replay_task.overall_passed === false ? '未通过' : '未判定'}
            valueStyle={{ color: detail.replay_task.overall_passed === true ? '#15803d' : detail.replay_task.overall_passed === false ? '#b91c1c' : '#475569' }}
          />
        </div>
      </Card>

      <Card title="回放任务" style={{ borderRadius: 18 }}>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="任务 ID">{detail.replay_task.id}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={STATUS_COLOR[detail.replay_task.status] || 'default'}>
              {STATUS_TEXT[detail.replay_task.status] || detail.replay_task.status}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="原始执行">{detail.original_execution.id}</Descriptions.Item>
          <Descriptions.Item label="回放执行">{detail.replay_execution.id}</Descriptions.Item>
          <Descriptions.Item label="比对模型">{llmNameMap[detail.replay_task.llm_model_id] || detail.replay_task.llm_model_id}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{formatLocalTime(detail.replay_task.created_at)}</Descriptions.Item>
          {detail.replay_task.error_message && (
            <Descriptions.Item label="错误信息" span={2}>{detail.replay_task.error_message}</Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      <Card title="比对结果" style={{ borderRadius: 18 }}>
        {comparison ? (
          <Space direction="vertical" style={{ width: '100%' }} size={16}>
            <Alert
              showIcon
              type={comparison.overall_passed ? 'success' : 'warning'}
              message={comparison.overall_passed ? '回放比对通过' : '回放比对未通过'}
              description={comparison.final_output_comparison?.reason || comparison.error_message || '-'}
            />
            {comparison.llm_count_check && (
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="期望次数">
                  {comparison.llm_count_check.expected_min} ~ {comparison.llm_count_check.expected_max}
                </Descriptions.Item>
                <Descriptions.Item label="实际次数">{comparison.llm_count_check.actual_count}</Descriptions.Item>
                <Descriptions.Item label="算法相似度" span={2}>
                  {comparison.final_output_comparison?.algorithm_similarity != null
                    ? comparison.final_output_comparison.algorithm_similarity.toFixed(3)
                    : '-'}
                </Descriptions.Item>
              </Descriptions>
            )}
          </Space>
        ) : (
          <Alert showIcon type={isRunning ? 'info' : 'warning'} message={isRunning ? '回放比对进行中' : '暂无回放比对结果'} />
        )}
      </Card>

      {detail.replay_task.baseline_source === 'scenario_baseline' && (
        <Card title="基线快照" style={{ borderRadius: 18 }}>
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="期望 LLM 次数">
              {String(snapshot.expected_min ?? '-')} ~ {String(snapshot.expected_max ?? '-')}
            </Descriptions.Item>
            <Descriptions.Item label="基线输出">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{baselineOutput || '-'}</pre>
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>Trace 区域</h3>
        <Space>
          <Select
            style={{ width: 220 }}
            value={selectedLlmId}
            onChange={setSelectedLlmId}
            options={llmModels.map(model => ({ label: model.name, value: model.id }))}
          />
          <Button icon={<ReloadOutlined />} disabled={detail.replay_task.status !== 'completed'} onClick={() => void handleRecompare()}>
            重新比对
          </Button>
        </Space>
      </div>

      {isReference ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <TracePanel title="原始 Trace" trace={originalTrace} loading={traceLoading} />
          <TracePanel title="回放 Trace" trace={replayTrace} loading={traceLoading} />
        </div>
      ) : (
        <TracePanel title="回放 Trace" trace={replayTrace} loading={traceLoading} />
      )}
    </div>
  )
}

export default ReplayDetail
