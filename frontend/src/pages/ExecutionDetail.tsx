import React, { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Card, Descriptions, Tag, Steps, Collapse, Alert, Spin, Result, Space, Button } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
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
      <Card title="执行详情">
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

      {execution.original_request && (
        <Card title="Agent 原始请求内容" style={{ marginTop: 16 }}>
          <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {execution.original_request}
          </pre>
        </Card>
      )}

      {execution.original_response && (
        <Card title="Agent 原始返回结果" style={{ marginTop: 16 }}>
          <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {execution.original_response}
          </pre>
        </Card>
      )}

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
            {trace.spans.map((span) => (
              <Collapse.Panel
                key={span.span_id}
                header={
                  <Space>
                    <Tag>{span.span_type}</Tag>
                    {span.name}
                    {span.input && <span> - {span.input.slice(0, 50)}...</span>}
                  </Space>
                }
              >
                {span.input && (
                  <div>
                    <div><strong>输入:</strong></div>
                    <pre style={{ background: '#f5f5f5', padding: 8 }}>{span.input}</pre>
                  </div>
                )}
                {span.output && (
                  <div style={{ marginTop: 8 }}>
                    <div><strong>输出:</strong></div>
                    <pre style={{ background: '#f5f5f5', padding: 8 }}>{span.output}</pre>
                  </div>
                )}
              </Collapse.Panel>
            ))}
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
