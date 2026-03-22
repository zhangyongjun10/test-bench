import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Descriptions, Tag, Steps, Collapse, Alert, Spin, Result, Space, Button } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, LeftOutlined } from '@ant-design/icons'
import { executionApi } from '../api/client'
import type { ExecutionJob, ExecutionTrace, Span } from '../api/types'

const STATUS_COLORS: Record<string, string> = {
  queued: 'blue',
  running: 'orange',
  pulling_trace: 'cyan',
  comparing: 'purple',
  completed: 'green',
  failed: 'red',
}

const STATUS_TEXT: Record<string, string> = {
  queued: '排队中',
  running: '执行中',
  pulling_trace: '拉取 Trace',
  comparing: '结果比对',
  completed: '完成',
  failed: '失败',
}

const ExecutionDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [execution, setExecution] = useState<ExecutionJob | null>(null)
  const [trace, setTrace] = useState<ExecutionTrace | null>(null)
  const [traceLoading, setTraceLoading] = useState(false)

  const loadData = async () => {
    if (!id) return
    setLoading(true)
    try {
      const res = await executionApi.get(id)
      setExecution(res.data)
      if (res.data.status === 'completed' || res.data.status === 'failed') {
        loadTrace()
      }
    } catch (e: any) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const loadTrace = async () => {
    if (!id) return
    setTraceLoading(true)
    try {
      const res = await executionApi.getTrace(id)
      setTrace(res.data)
    } catch (e: any) {
      console.error(e)
    } finally {
      setTraceLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [id])

  if (loading) {
    return <Spin size="large" style={{ display: 'block', margin: '50px auto' }} />
  }

  if (!execution) {
    return <Result status="404" title="执行不存在" />
  }

  const getDuration = () => {
    if (!execution.started_at || !execution.completed_at) return '-'
    return `${(new Date(execution.completed_at).getTime() - new Date(execution.started_at).getTime()) / 1000}s`
  }

  return (
    <div>
      <Card
        title="执行详情"
        extra={
          <Button type="primary" ghost icon={<LeftOutlined />} onClick={() => navigate('/executions')}>
            返回列表
          </Button>
        }
      >
        <Descriptions bordered column={2}>
          <Descriptions.Item label="执行ID">{execution.id}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={STATUS_COLORS[execution.status] || 'gray'}>
              {STATUS_TEXT[execution.status] || execution.status}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Agent ID">{execution.agent_id}</Descriptions.Item>
          <Descriptions.Item label="场景 ID">{execution.scenario_id}</Descriptions.Item>
          <Descriptions.Item label="Trace ID">{execution.trace_id || '-'}</Descriptions.Item>
          <Descriptions.Item label="比对分数">
            {execution.comparison_score != null ? execution.comparison_score.toFixed(2) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="比对结果">
            {execution.comparison_passed === true ? (
              <Tag color="green">通过</Tag>
            ) : execution.comparison_passed === false ? (
              <Tag color="red">不通过</Tag>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="耗时">{getDuration()}</Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {new Date(new Date(execution.created_at).getTime() + 8 * 60 * 60 * 1000).toLocaleString('zh-CN')}
          </Descriptions.Item>
          <Descriptions.Item label="完成时间">
            {execution.completed_at ? new Date(new Date(execution.completed_at).getTime() + 8 * 60 * 60 * 1000).toLocaleString('zh-CN') : '-'}
          </Descriptions.Item>
        </Descriptions>

        {execution.error_message && (
          <Alert
            message="执行错误"
            description={execution.error_message}
            type="error"
            style={{ marginTop: 16 }}
          />
        )}
      </Card>

      {trace && trace.spans.length > 0 && (
        <Card title="全链路回放" style={{ marginTop: 16 }}>
          <Steps
            direction="vertical"
            current={trace.spans.length}
            items={trace.spans.map((span, i) => ({
              title: `${span.name} (${span.span_type})`,
              description: (
                <div>
                  <div>耗时: {span.duration_ms}ms</div>
                  {span.ttft_ms && <div>TTFT: {span.ttft_ms}ms</div>}
                  {span.tpot_ms && <div>TPOT: {span.tpot_ms}ms</div>}
                </div>
              ),
            }))}
          />

          <Collapse style={{ marginTop: 16 }}>
            {trace.spans.map((span) => {
              // 对于 LLM 类型 span，尝试提取 lastAssistant.content
              const isLlmType = span.span_type === 'llm' || span.span_type === 'LLM';
              let displayOutput = span.output;
              if (isLlmType && span.output) {
                try {
                  const outputJson = JSON.parse(span.output);
                  if (outputJson?.lastAssistant?.content) {
                    const content = outputJson.lastAssistant.content;
                    // 如果 content 是 OpenAI 格式数组 [{type: "text", text: "..."}]
                    if (Array.isArray(content)) {
                      displayOutput = content
                        .filter(item => item.type === 'text' && item.text)
                        .map(item => item.text)
                        .join('\n');
                    } else if (typeof content === 'string') {
                      displayOutput = content;
                    }
                    // 如果是对象保持 JSON 字符串化
                    else if (typeof content === 'object') {
                      displayOutput = JSON.stringify(content, null, 2);
                    }
                  }
                } catch (e) {
                  // 解析失败，保持原样
                }
              }

              return (
              <Collapse.Panel
                key={span.span_id}
                header={
                  <Space>
                    <Tag>{span.span_type}</Tag>
                    {span.name}
                    {span.input && <span> - {span.input.slice(0, 50)}...</span>}
                    {isLlmType && displayOutput !== span.output && <Tag color="blue">简化</Tag>}
                  </Space>
                }
              >
                {span.input && (
                  <div>
                    <div><strong>输入:</strong></div>
                    <pre style={{ background: '#f5f5f5', padding: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: '400px', overflowY: 'auto' }}>{span.input}</pre>
                  </div>
                )}
                {displayOutput && (
                  <div style={{ marginTop: 8 }}>
                    <div><strong>输出:</strong></div>
                    <pre style={{ background: '#f5f5f5', padding: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: '400px', overflowY: 'auto' }}>{displayOutput}</pre>
                  </div>
                )}
              </Collapse.Panel>
              );
            })}
          </Collapse>
        </Card>
      )}

      {traceLoading && (
        <Card style={{ marginTop: 16 }}>
          <Spin />
        </Card>
      )}
    </div>
  )
}

export default ExecutionDetail
