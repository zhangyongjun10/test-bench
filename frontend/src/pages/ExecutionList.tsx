import { useEffect, useMemo, useState } from 'react'
import { Button, Form, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, message } from 'antd'
import { DeleteOutlined, EyeOutlined, PlusOutlined, RetweetOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { agentApi, executionApi, llmApi, replayApi, scenarioApi, systemApi } from '../api/client'
import type {
  Agent,
  CreateConcurrentExecutionRequest,
  ExecutionJob,
  LLMModel,
  ReplayBaselineSource,
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
  comparing: '比对中',
  completed: '完成',
  completed_with_mismatch: '完成(比对未通过)',
  failed: '失败',
}

const formatLocalTime = (value: string) => {
  if (!value) {
    return '-'
  }
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

const generateIdempotencyKey = () => {
  if (typeof globalThis !== 'undefined' && globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID()
  }
  return `fallback-${Date.now()}`
}

// 解析 URL 中的正整数分页参数，非法值统一回退到默认分页，避免列表初始化异常。
const parsePositiveInteger = (value: string | null, fallback: number) => {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

// 执行创建表单值，只暴露用户需要选择的 Agent、场景、比对模型和并发数。
type ExecutionFormValues = {
  agent_id: string
  scenario_id: string
  llm_model_id: string
  mode: 'single' | 'concurrent'
  concurrency?: number
}

const ExecutionList = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const [executions, setExecutions] = useState<ExecutionJob[]>([])
  const [total, setTotal] = useState(0)
  const [agents, setAgents] = useState<Agent[]>([])
  const [allScenarios, setAllScenarios] = useState<Scenario[]>([])
  const [filteredScenarios, setFilteredScenarios] = useState<Scenario[]>([])
  const [llms, setLlms] = useState<LLMModel[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState(() => searchParams.get('agent_id') || '')
  const [selectedScenarioId, setSelectedScenarioId] = useState(() => searchParams.get('scenario_id') || '')
  const [currentPage, setCurrentPage] = useState(() => parsePositiveInteger(searchParams.get('page'), 1))
  const [pageSize, setPageSize] = useState(() => parsePositiveInteger(searchParams.get('page_size'), 10))
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [replayModalVisible, setReplayModalVisible] = useState(false)
  const [replaySubmitting, setReplaySubmitting] = useState(false)
  const [selectedReplayExecution, setSelectedReplayExecution] = useState<ExecutionJob | null>(null)
  const [concurrentExecutionMaxConcurrency, setConcurrentExecutionMaxConcurrency] = useState<number | null>(null)
  const [form] = Form.useForm<ExecutionFormValues>()
  const [replayForm] = Form.useForm()

  const scenarioNameMap = useMemo(
    () => Object.fromEntries(allScenarios.map(scenario => [scenario.id, scenario.name])),
    [allScenarios],
  )
  const llmNameMap = useMemo(() => Object.fromEntries(llms.map(model => [model.id, model.name])), [llms])

  // 同步执行列表筛选和分页到 URL，详情页返回时可恢复原始页码和筛选条件。
  const syncListSearch = (nextState: {
    agentId?: string
    scenarioId?: string
    page?: number
    size?: number
  }) => {
    const agentId = nextState.agentId ?? selectedAgentId
    const scenarioId = nextState.scenarioId ?? selectedScenarioId
    const page = nextState.page ?? currentPage
    const size = nextState.size ?? pageSize
    const nextParams = new URLSearchParams()
    if (agentId) {
      nextParams.set('agent_id', agentId)
    }
    if (scenarioId) {
      nextParams.set('scenario_id', scenarioId)
    }
    if (page > 1) {
      nextParams.set('page', String(page))
    }
    if (size !== 10) {
      nextParams.set('page_size', String(size))
    }
    setSearchParams(nextParams, { replace: true })
  }

  const loadAgents = async () => {
    const res = await agentApi.list()
    setAgents(res.data || [])
  }

  const loadScenarios = async () => {
    const res = await scenarioApi.list()
    const scenarios = res.data || []
    setAllScenarios(scenarios)
    setFilteredScenarios(selectedAgentId ? scenarios.filter(scenario => scenario.agent_id === selectedAgentId) : [])
  }

  const loadLlms = async () => {
    const res = await llmApi.list()
    setLlms(res.data || [])
  }

  // 从后端读取前端运行时配置；并发上限以后只需要改后端环境变量，不需要重新改页面常量。
  const loadRuntimeConfig = async () => {
    const res = await systemApi.getRuntimeConfig()
    setConcurrentExecutionMaxConcurrency(res.data.concurrent_execution_max_concurrency)
  }

  const loadExecutions = async (
    page = currentPage,
    size = pageSize,
    agentId = selectedAgentId,
    scenarioId = selectedScenarioId,
  ) => {
    setLoading(true)
    try {
      const res = await executionApi.list(agentId || undefined, scenarioId || undefined, size, (page - 1) * size)
      setExecutions(res.data.items || [])
      setTotal(res.data.total || 0)
    } catch (error: any) {
      message.error(error.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void Promise.all([loadAgents(), loadScenarios(), loadLlms(), loadRuntimeConfig()]).catch((error: any) => {
      message.error(error.message)
    })
  }, [])

  useEffect(() => {
    const nextAgentId = searchParams.get('agent_id') || ''
    const nextScenarioId = searchParams.get('scenario_id') || ''
    const nextPage = parsePositiveInteger(searchParams.get('page'), 1)
    const nextPageSize = parsePositiveInteger(searchParams.get('page_size'), 10)

    setSelectedAgentId(nextAgentId)
    setSelectedScenarioId(nextScenarioId)
    setCurrentPage(nextPage)
    setPageSize(nextPageSize)
    void loadExecutions(nextPage, nextPageSize, nextAgentId, nextScenarioId)
  }, [searchParams])

  useEffect(() => {
    setFilteredScenarios(selectedAgentId ? allScenarios.filter(scenario => scenario.agent_id === selectedAgentId) : [])
  }, [allScenarios, selectedAgentId])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadExecutions()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [currentPage, pageSize, selectedAgentId, selectedScenarioId])

  const openCreateModal = () => {
    form.resetFields()
    form.setFieldsValue({
      mode: 'single',
      concurrency: 1,
    })
    setModalVisible(true)
  }

  const handleModalAgentChange = (agentId: string) => {
    const scenarios = allScenarios.filter(scenario => scenario.agent_id === agentId)
    setFilteredScenarios(scenarios)
    form.setFieldValue('scenario_id', undefined)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (values.mode === 'concurrent') {
        const scenario = allScenarios.find(item => item.id === values.scenario_id)
        const llm = llms.find(item => item.id === values.llm_model_id)
        if (!scenario || !llm) {
          throw new Error('场景或比对模型不存在')
        }
        const payload: CreateConcurrentExecutionRequest = {
          input: scenario.prompt,
          concurrency: values.concurrency || 1,
          scenario_id: values.scenario_id,
          llm_model_id: values.llm_model_id,
          agent_id: values.agent_id,
        }
        if (concurrentExecutionMaxConcurrency === null) {
          throw new Error('系统运行配置加载中，请稍后再试')
        }
        if (payload.concurrency > concurrentExecutionMaxConcurrency) {
          throw new Error(`并发数超过系统上限，当前上限为 ${concurrentExecutionMaxConcurrency}`)
        }
        await executionApi.createConcurrent(payload)
        message.success('并发执行已启动')
      } else {
        await executionApi.create({
          agent_id: values.agent_id,
          scenario_id: values.scenario_id,
          llm_model_id: values.llm_model_id,
        })
        message.success('执行已触发')
      }
      setModalVisible(false)
      setCurrentPage(1)
      syncListSearch({ page: 1 })
      await loadExecutions(1, pageSize)
    } catch (error: any) {
      if (error?.errorFields) {
        return
      }
      message.error(error.message)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await executionApi.delete(id)
      message.success('删除成功')
      const nextPage = executions.length === 1 && currentPage > 1 ? currentPage - 1 : currentPage
      setCurrentPage(nextPage)
      syncListSearch({ page: nextPage })
      await loadExecutions(nextPage, pageSize)
    } catch (error: any) {
      message.error(error.message)
    }
  }

  const openReplayModal = (execution: ExecutionJob) => {
    setSelectedReplayExecution(execution)
    replayForm.setFieldsValue({
      baseline_source: 'reference_execution',
      llm_model_id: execution.llm_model_id || llms[0]?.id,
      idempotency_key: generateIdempotencyKey(),
    })
    setReplayModalVisible(true)
  }

  const handleReplaySubmit = async () => {
    if (!selectedReplayExecution) {
      return
    }
    setReplaySubmitting(true)
    try {
      const values = await replayForm.validateFields()
      const res = await replayApi.create({
        original_execution_id: selectedReplayExecution.id,
        baseline_source: values.baseline_source as ReplayBaselineSource,
        llm_model_id: values.llm_model_id,
        idempotency_key: values.idempotency_key,
      })
      message.success('链路回放任务已创建')
      setReplayModalVisible(false)
      navigate(`/replays/${res.data.id}`)
    } catch (error: any) {
      if (!error?.errorFields) {
        message.error(error.message)
      }
    } finally {
      setReplaySubmitting(false)
    }
  }

  const columns: ColumnsType<ExecutionJob> = [
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 140,
      render: value => <Tag color={STATUS_COLORS[value] || 'default'}>{STATUS_TEXT[value] || value}</Tag>,
    },
    {
      title: '测试场景',
      dataIndex: 'scenario_id',
      key: 'scenario_id',
      width: 220,
      render: value => scenarioNameMap[value] || value,
    },
    {
      title: '比对模型',
      dataIndex: 'llm_model_id',
      key: 'llm_model_id',
      width: 220,
      render: value => (value ? llmNameMap[value] || value : '-'),
    },
    {
      title: '比对结果',
      dataIndex: 'comparison_passed',
      key: 'comparison_passed',
      width: 120,
      render: value => (value === true ? <Tag color="green">通过</Tag> : value === false ? <Tag color="red">未通过</Tag> : '-'),
    },
    {
      title: '回放',
      dataIndex: 'replay_count',
      key: 'replay_count',
      width: 120,
      render: value => (value && value > 0 ? <Tag color="blue">已回放 {value} 次</Tag> : '-'),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: formatLocalTime,
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      fixed: 'right',
      render: (_, record) => (
        <Space size="middle">
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() =>
              navigate(`/execution/${record.id}`, {
                state: { from: `${location.pathname}${location.search}` },
              })
            }
          >
            详情
          </Button>
          <Button
            type="link"
            size="small"
            icon={<RetweetOutlined />}
            disabled={record.status !== 'completed' && record.status !== 'completed_with_mismatch'}
            onClick={() => openReplayModal(record)}
          >
            回放
          </Button>
          <Popconfirm title="确认删除这条执行记录吗？" onConfirm={() => void handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Select
          placeholder="筛选 Agent"
          style={{ width: 220 }}
          allowClear
          value={selectedAgentId || undefined}
          onChange={value => {
            const nextAgentId = value || ''
            setSelectedAgentId(nextAgentId)
            setSelectedScenarioId('')
            setCurrentPage(1)
            syncListSearch({ agentId: nextAgentId, scenarioId: '', page: 1 })
          }}
          options={agents.map(agent => ({ label: agent.name, value: agent.id }))}
        />
        <Select
          placeholder="筛选场景"
          style={{ width: 220 }}
          allowClear
          value={selectedScenarioId || undefined}
          onChange={value => {
            const nextScenarioId = value || ''
            setSelectedScenarioId(nextScenarioId)
            setCurrentPage(1)
            syncListSearch({ scenarioId: nextScenarioId, page: 1 })
          }}
          options={filteredScenarios.map(scenario => ({ label: scenario.name, value: scenario.id }))}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
          新建执行
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={executions}
        loading={loading}
        rowKey="id"
        pagination={{
          current: currentPage,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: value => `共 ${value} 条`,
          onChange: (page, size) => {
            const nextSize = size || pageSize
            setCurrentPage(page)
            setPageSize(nextSize)
            syncListSearch({ page, size: nextSize })
          },
        }}
      />

      <Modal title="新建执行" open={modalVisible} onOk={() => void handleSubmit()} onCancel={() => setModalVisible(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="mode" label="执行方式" rules={[{ required: true, message: '请选择执行方式' }]}>
            <Select
              options={[
                { label: '单次执行', value: 'single' },
                { label: '并发执行', value: 'concurrent' },
              ]}
            />
          </Form.Item>
          <Form.Item name="agent_id" label="Agent" rules={[{ required: true, message: '请选择 Agent' }]}>
            <Select placeholder="选择 Agent" options={agents.map(agent => ({ label: agent.name, value: agent.id }))} onChange={handleModalAgentChange} />
          </Form.Item>
          <Form.Item name="scenario_id" label="测试场景" rules={[{ required: true, message: '请选择场景' }]}>
            <Select placeholder="选择场景" options={filteredScenarios.map(scenario => ({ label: scenario.name, value: scenario.id }))} />
          </Form.Item>
          <Form.Item name="llm_model_id" label="比对模型" rules={[{ required: true, message: '请选择比对模型' }]}>
            <Select placeholder="选择比对模型" options={llms.map(model => ({ label: model.name, value: model.id }))} />
          </Form.Item>

          <Form.Item noStyle shouldUpdate>
            {({ getFieldValue }) =>
              getFieldValue('mode') === 'concurrent' ? (
                <>
                  <Form.Item
                    name="concurrency"
                    label="并发数"
                    extra={
                      concurrentExecutionMaxConcurrency === null
                        ? '正在读取系统并发上限'
                        : `当前系统上限：${concurrentExecutionMaxConcurrency}`
                    }
                    rules={[{ required: true, message: '请输入并发数' }]}
                  >
                    <InputNumber
                      min={1}
                      max={concurrentExecutionMaxConcurrency ?? undefined}
                      style={{ width: '100%' }}
                    />
                  </Form.Item>
                </>
              ) : null
            }
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="链路回放"
        open={replayModalVisible}
        confirmLoading={replaySubmitting}
        onOk={() => void handleReplaySubmit()}
        onCancel={() => setReplayModalVisible(false)}
        okText="确认回放"
        cancelText="取消"
      >
        <Form form={replayForm} layout="vertical">
          <Form.Item label="原始执行">
            <div style={{ color: '#475569', wordBreak: 'break-all' }}>{selectedReplayExecution?.id || '-'}</div>
          </Form.Item>
          <Form.Item name="baseline_source" label="比较基准" rules={[{ required: true, message: '请选择比较基准' }]}>
            <Select
              options={[
                { label: '与当前执行比较', value: 'reference_execution' },
                { label: '与场景基线比较', value: 'scenario_baseline' },
              ]}
            />
          </Form.Item>
          <Form.Item name="llm_model_id" label="比对模型" rules={[{ required: true, message: '请选择比对模型' }]}>
            <Select options={llms.map(model => ({ label: model.name, value: model.id }))} />
          </Form.Item>
          <Form.Item name="idempotency_key" hidden>
            <input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ExecutionList
