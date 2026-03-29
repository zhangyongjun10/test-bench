import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Descriptions, Tag, Steps, Collapse, Alert, Spin, Result, Space, Button, Statistic, Divider, message, Select, Modal } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, LeftOutlined, ReloadOutlined, PushpinOutlined } from '@ant-design/icons'
import { executionApi, scenarioApi, scenarioApiExtended, llmApi } from '../api/client'
import type { ExecutionJob, ExecutionTrace, DetailedComparisonResult, LLMModel } from '../api/types'

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
  completed_with_mismatch: '完成(比对不通过)',
  failed: '失败',
}

const POLL_INTERVAL = 2000  // 2 seconds
const MAX_POLL_TIME = 2 * 60 * 1000  // 2 minutes

import type { Scenario } from '../api/types'

const ExecutionDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [execution, setExecution] = useState<ExecutionJob | null>(null)
  const [scenarioName, setScenarioName] = useState<string>('')
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [trace, setTrace] = useState<ExecutionTrace | null>(null)
  const [traceLoading, setTraceLoading] = useState(false)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonDetail, setComparisonDetail] = useState<DetailedComparisonResult | null>(null)
  const [pollTimeout, setPollTimeout] = useState(false)
  const [llmModels, setLlmModels] = useState<LLMModel[]>([])
  const [selectedLlmId, setSelectedLlmId] = useState<string | undefined>(undefined)
  const [llmLoading, setLlmLoading] = useState(false)
  const [llmModalVisible, setLlmModalVisible] = useState(false)

  // 加载 LLM 模型列表
  const loadLlmModels = async () => {
    setLlmLoading(true)
    try {
      const res = await llmApi.list()
      setLlmModels(res.data || [])
    } catch (e) {
      console.error('Failed to load LLM models:', e)
    } finally {
      setLlmLoading(false)
    }
  }

  const handleRecompareClick = () => {
    // 如果已经有 llm_model_id，默认选中
    if (execution?.llm_model_id && !selectedLlmId) {
      setSelectedLlmId(execution.llm_model_id)
    }
    setLlmModalVisible(true)
  }

  const confirmRecompare = async () => {
    setLlmModalVisible(false)
    try {
      await executionApi.recompare(id!, selectedLlmId)
      startPolling()
    } catch (e: any) {
      console.error('Failed to trigger recompare:', e)
    }
  }

  useEffect(() => {
    loadLlmModels()
  }, [])

  const loadComparison = async () => {
    if (!id) return
    try {
      const res = await executionApi.getComparison(id)
      setComparisonDetail(res.data)
      // 如果还在处理中，继续轮询
      if (res.data.status === 'pending' || res.data.status === 'processing') {
        return false
      }
      return true
    } catch (e: any) {
      console.error('Failed to load comparison:', e)
      return true
    }
  }

  const startPolling = () => {
    setPollTimeout(false)
    setComparisonLoading(true)
    const startTime = Date.now()
    const interval = setInterval(async () => {
      const done = await loadComparison()
      if (done || Date.now() - startTime > MAX_POLL_TIME) {
        clearInterval(interval)
        setComparisonLoading(false)
        if (Date.now() - startTime > MAX_POLL_TIME) {
          setPollTimeout(true)
        }
      }
    }, POLL_INTERVAL)
  }


  const handleSetBaseline = async () => {
    if (!id || !execution) return
    try {
      await scenarioApiExtended.setBaseline(execution.scenario_id, id)
      message.success('设置基线成功')
    } catch (e: any) {
      console.error('Failed to set baseline:', e)
      message.error('设置基线失败: ' + e.message)
    }
  }

  const loadData = async () => {
    if (!id) return
    setLoading(true)
    try {
      const res = await executionApi.get(id)
      setExecution(res.data)
      // 如果 execution 已有 llm_model_id，默认选中
      if (res.data.llm_model_id) {
        setSelectedLlmId(res.data.llm_model_id)
      }
      // 获取场景信息
      if (res.data.scenario_id) {
        try {
          const scenarioRes = await scenarioApi.get(res.data.scenario_id)
          setScenarioName(scenarioRes.data.name)
          setScenario(scenarioRes.data)
        } catch (e) {
          // 获取失败，显示 id
          setScenarioName(res.data.scenario_id)
        }
      } else {
        setScenarioName('')
      }
      if (res.data.status === 'completed' || res.data.status === 'failed' || res.data.status === 'completed_with_mismatch') {
        loadTrace()
        // 如果已经有比对结果，加载详情
        startPolling()
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
          <Descriptions.Item label="测试场景">{scenarioName || execution.scenario_id}</Descriptions.Item>
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
          <Descriptions.Item label="过程阈值">
            {scenario ? scenario.process_threshold : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="结果阈值">
            {scenario ? scenario.result_threshold : '-'}
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
            items={trace.spans.map((span) => ({
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

      {/* 比对详情卡片 - 始终显示，确保重新比对按钮总是可用 */}
      <Card
        title="比对详情"
        style={{ marginTop: 16 }}
        extra={
          <Space>
            {execution && (execution.status === 'completed' || execution.status === 'completed_with_mismatch' || execution.status === 'failed') && (
              <Button
                icon={<PushpinOutlined />}
                onClick={handleSetBaseline}
              >
                设为基线
              </Button>
            )}
            <Button
              icon={<ReloadOutlined />}
              onClick={handleRecompareClick}
              loading={comparisonLoading}
            >
              重新比对
            </Button>
          </Space>
        }
      >
          {pollTimeout && (
            <Alert
              message="轮询超时"
              description="比对仍在进行中，请稍后手动刷新查看结果"
              type="warning"
              style={{ marginBottom: 16 }}
            />
          )}

          {comparisonDetail?.status === 'failed' && (
            <Alert
              message="比对失败"
              description={comparisonDetail.error_message || '未知错误'}
              type="error"
              style={{ marginBottom: 16 }}
            />
          )}

          {comparisonLoading && (
            <div style={{ textAlign: 'center', padding: '20px' }}>
              <Spin />
              <div style={{ marginTop: 8 }}>比对进行中...</div>
            </div>
          )}

          {!comparisonLoading && (
            <>
              {!comparisonDetail && (
                <Alert
                  message="未进行比对"
                  description="当前执行还没有进行过比对。点击右上方'重新比对'开始自动比对，完成后就可以查看比对结果。"
                  type="info"
                  showIcon
                  style={{ marginBottom: 16 }}
                />
              )}
              {comparisonDetail && (
                <>
                  {comparisonDetail.process_score == null && comparisonDetail.result_score == null && (
                    <Alert
                      message="未设置基线"
                      description="当前场景没有设置过程基线和结果基线，所以无法进行比对。可以点击右上方'设为基线'将当前执行设置为基线。"
                      type="info"
                      showIcon
                      style={{ marginBottom: 16 }}
                    />
                  )}
                  <Space size="large" wrap>
                    {comparisonDetail.process_score != null && (
                      <Statistic
                        title="过程分数"
                        value={comparisonDetail.process_score}
                        suffix="/ 100"
                        valueStyle={{
                          color: comparisonDetail.process_score >= 60 ? '#3f8600' : '#cf1322',
                        }}
                      />
                    )}
                    {comparisonDetail.result_score != null && (
                      <Statistic
                        title="结果分数"
                        value={comparisonDetail.result_score}
                        suffix="/ 100"
                        valueStyle={{
                          color: comparisonDetail.result_score >= 60 ? '#3f8600' : '#cf1322',
                        }}
                      />
                    )}
                    <Statistic
                      title="总体结果"
                      value={comparisonDetail.overall_passed ? '通过' : '不通过'}
                      valueStyle={{
                        color: comparisonDetail.overall_passed ? '#3f8600' : '#cf1322',
                      }}
                      prefix={comparisonDetail.overall_passed ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                    />
                  </Space>

                  <Divider />

                  <Collapse defaultActiveKey={['tools']}>
                    <Collapse.Panel
                      header={`工具调用比对 (${comparisonDetail.tool_comparisons.filter(t => t.matched).length}/${comparisonDetail.tool_comparisons.length})`}
                      key="tools"
                    >
                      {comparisonDetail.tool_comparisons.map((tool, idx) => (
                        <div key={idx} style={{ marginBottom: 16, border: '1px solid #f0f0f0', padding: 12, borderRadius: 4 }}>
                          <Space>
                            <Tag color={tool.matched ? 'blue' : 'red'}>{tool.tool_name}</Tag>
                            <Tag color={tool.score >= 0.5 ? 'green' : 'red'}>
                              {(tool.score * 100).toFixed(1)}
                            </Tag>
                            {!tool.matched && <Tag color="orange">未匹配</Tag>}
                          </Space>
                          <div style={{ marginTop: 8 }}>
                            <small style={{ color: '#888' }}>{tool.reason}</small>
                          </div>
                          {tool.baseline_input && (
                            <div style={{ marginTop: 8 }}>
                              <div><strong>基线输入:</strong></div>
                              <pre style={{ background: '#f5f5f5', padding: 8, fontSize: 12, maxHeight: 200, overflow: 'auto' }}>{tool.baseline_input}</pre>
                            </div>
                          )}
                          {tool.actual_input && (
                            <div style={{ marginTop: 8 }}>
                              <div><strong>实际输入:</strong></div>
                              <pre style={{ background: '#f5f5f5', padding: 8, fontSize: 12, maxHeight: 200, overflow: 'auto' }}>{tool.actual_input}</pre>
                            </div>
                          )}
                          {tool.baseline_output && (
                            <div style={{ marginTop: 8 }}>
                              <div><strong>基线输出:</strong></div>
                              <pre style={{ background: '#f5f5f5', padding: 8, fontSize: 12, maxHeight: 200, overflow: 'auto' }}>{tool.baseline_output}</pre>
                            </div>
                          )}
                          {tool.actual_output && (
                            <div style={{ marginTop: 8 }}>
                              <div><strong>实际输出:</strong></div>
                              <pre style={{ background: '#f5f5f5', padding: 8, fontSize: 12, maxHeight: 200, overflow: 'auto' }}>{tool.actual_output}</pre>
                            </div>
                          )}
                        </div>
                      ))}
                    </Collapse.Panel>

                    {comparisonDetail.llm_comparison && (
                      <Collapse.Panel header="LLM 结果比对" key="llm">
                        <div style={{ marginBottom: 16 }}>
                          <Space>
                            <Tag color={comparisonDetail.llm_comparison.score >= 0.5 ? 'green' : 'red'}>
                              LLM 分数: {(comparisonDetail.llm_comparison.score * 100).toFixed(1)}
                            </Tag>
                            <Tag color="blue">
                              算法相似度: {(comparisonDetail.llm_comparison.similarity * 100).toFixed(1)}
                            </Tag>
                          </Space>
                          <div style={{ marginTop: 8 }}>
                            <small style={{ color: '#888' }}>{comparisonDetail.llm_comparison.reason}</small>
                          </div>
                          <div style={{ marginTop: 8 }}>
                            <div><strong>基线输出:</strong></div>
                            <pre style={{ background: '#f5f5f5', padding: 8, fontSize: 12, maxHeight: 300, overflow: 'auto' }}>{comparisonDetail.llm_comparison.baseline_output}</pre>
                          </div>
                          <div style={{ marginTop: 8 }}>
                            <div><strong>实际输出:</strong></div>
                            <pre style={{ background: '#f5f5f5', padding: 8, fontSize: 12, maxHeight: 300, overflow: 'auto' }}>{comparisonDetail.llm_comparison.actual_output}</pre>
                          </div>
                        </div>
                      </Collapse.Panel>
                    )}
                  </Collapse>
                </>
              )}
            </>
          )}
        </Card>

        <Modal
          title="选择 LLM 模型（用于比对验证）"
          open={llmModalVisible}
          onCancel={() => setLlmModalVisible(false)}
          onOk={confirmRecompare}
          confirmLoading={comparisonLoading}
          okText="开始比对"
          cancelText="取消"
        >
          <div style={{ marginBottom: 16 }}>
            <p>选择一个 LLM 模型用于语义验证。如果留空则不进行 LLM 验证，仅使用算法相似度打分。</p>
          </div>
          <Select
            placeholder="选择 LLM 模型"
            allowClear
            style={{ width: '100%' }}
            loading={llmLoading}
            options={llmModels.map(m => ({ label: m.name, value: m.id }))}
            value={selectedLlmId || execution?.llm_model_id || undefined}
            onChange={setSelectedLlmId}
          />
        </Modal>
    </div>
  )
}

export default ExecutionDetail
