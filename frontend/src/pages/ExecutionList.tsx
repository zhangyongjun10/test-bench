import { useEffect, useMemo, useState } from 'react'
import { Button, Form, Modal, Popconfirm, Select, Space, Table, Tag, message } from 'antd'
import { DeleteOutlined, EyeOutlined, PlusOutlined, RetweetOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'

import { agentApi, executionApi, llmApi, replayApi, scenarioApi } from '../api/client'
import type { Agent, ExecutionJob, LLMModel, ReplayBaselineSource, Scenario } from '../api/types'

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

const formatLocalTime = (value: string) => {
  if (!value) {
    return '-'
  }
  const isoLikeValue = value.includes('T') ? value : value.replace(' ', 'T')
  const normalizedValue =
    /(?:Z|[+-]\d{2}:\d{2})$/.test(isoLikeValue) ? isoLikeValue : `${isoLikeValue}Z`
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

  if (typeof globalThis !== 'undefined' && globalThis.crypto?.getRandomValues) {
    const bytes = new Uint8Array(16)
    globalThis.crypto.getRandomValues(bytes)
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
    return [
      hex.slice(0, 8),
      hex.slice(8, 12),
      hex.slice(12, 16),
      hex.slice(16, 20),
      hex.slice(20, 32),
    ].join('-')
  }

  const timestamp = Date.now().toString(16)
  const random = Math.random().toString(16).slice(2)
  return `fallback-${timestamp}-${random}`
}

const ExecutionList = () => {
  const navigate = useNavigate()
  const [executions, setExecutions] = useState<ExecutionJob[]>([])
  const [total, setTotal] = useState(0)
  const [agents, setAgents] = useState<Agent[]>([])
  const [allScenarios, setAllScenarios] = useState<Scenario[]>([])
  const [filteredScenarios, setFilteredScenarios] = useState<Scenario[]>([])
  const [llms, setLlms] = useState<LLMModel[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState("")
  const [selectedScenarioId, setSelectedScenarioId] = useState("")
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [replayModalVisible, setReplayModalVisible] = useState(false)
  const [replaySubmitting, setReplaySubmitting] = useState(false)
  const [selectedReplayExecution, setSelectedReplayExecution] = useState<ExecutionJob | null>(null)
  const [form] = Form.useForm()
  const [replayForm] = Form.useForm()

  const scenarioNameMap = useMemo(
    () => Object.fromEntries(allScenarios.map(scenario => [scenario.id, scenario.name])),
    [allScenarios],
  )
  const llmNameMap = useMemo(
    () => Object.fromEntries(llms.map(model => [model.id, model.name])),
    [llms],
  )

  const loadAgents = async () => {
    const res = await agentApi.list()
    setAgents(res.data || [])
  }

  const loadScenarios = async () => {
    const res = await scenarioApi.list()
    const scenarios = res.data || []
    setAllScenarios(scenarios)
    if (selectedAgentId) {
      setFilteredScenarios(scenarios.filter(scenario => scenario.agent_id === selectedAgentId))
    } else {
      setFilteredScenarios([])
    }
  }

  const loadLlms = async () => {
    const res = await llmApi.list()
    setLlms(res.data || [])
  }

  const loadExecutions = async (page = currentPage, size = pageSize) => {
    setLoading(true)
    try {
      const res = await executionApi.list(
        selectedAgentId || undefined,
        selectedScenarioId || undefined,
        size,
        (page - 1) * size,
      )
      setExecutions(res.data.items || [])
      setTotal(res.data.total || 0)
    } catch (error: any) {
      message.error(error.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void Promise.all([loadAgents(), loadScenarios(), loadLlms(), loadExecutions()]).catch((error: any) => {
      message.error(error.message)
    })
  }, [])

  useEffect(() => {
    setCurrentPage(1)
    void loadExecutions(1, pageSize)
  }, [selectedAgentId, selectedScenarioId])

  useEffect(() => {
    if (selectedAgentId) {
      setFilteredScenarios(allScenarios.filter(scenario => scenario.agent_id === selectedAgentId))
    } else {
      setFilteredScenarios([])
    }
  }, [allScenarios, selectedAgentId])

  const openCreateModal = () => {
    form.resetFields()
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
      await executionApi.create(values)
      message.success('执行已触发')
      setModalVisible(false)
      setCurrentPage(1)
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
      await loadExecutions(nextPage, pageSize)
    } catch (error: any) {
      message.error(error.message)
    }
  }

  const openReplayModal = (execution: ExecutionJob) => {
    const defaultModelId = execution.llm_model_id || llms[0]?.id
    setSelectedReplayExecution(execution)
    replayForm.setFieldsValue({
      baseline_source: 'reference_execution',
      llm_model_id: defaultModelId,
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
      render: value =>
        value === true ? (
          <Tag color="green">通过</Tag>
        ) : value === false ? (
          <Tag color="red">未通过</Tag>
        ) : (
          '-'
        ),
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
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/execution/${record.id}`)}>
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
            setSelectedAgentId(value || '')
            setSelectedScenarioId('')
          }}
          options={agents.map(agent => ({ label: agent.name, value: agent.id }))}
        />
        <Select
          placeholder="筛选场景"
          style={{ width: 220 }}
          allowClear
          value={selectedScenarioId || undefined}
          onChange={value => setSelectedScenarioId(value || '')}
          options={filteredScenarios.map(scenario => ({ label: scenario.name, value: scenario.id }))}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
          触发执行
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
            void loadExecutions(page, nextSize)
          },
        }}
      />

      <Modal
        title="触发新执行"
        open={modalVisible}
        onOk={() => void handleSubmit()}
        onCancel={() => setModalVisible(false)}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="agent_id" label="Agent" rules={[{ required: true, message: '请选择 Agent' }]}>
            <Select
              placeholder="选择 Agent"
              options={agents.map(agent => ({ label: agent.name, value: agent.id }))}
              onChange={handleModalAgentChange}
            />
          </Form.Item>

          <Form.Item name="scenario_id" label="测试场景" rules={[{ required: true, message: '请选择场景' }]}>
            <Select
              placeholder="选择场景"
              options={filteredScenarios.map(scenario => ({ label: scenario.name, value: scenario.id }))}
            />
          </Form.Item>

          <Form.Item
            name="llm_model_id"
            label="比对模型"
            rules={[{ required: true, message: '请选择比对模型' }]}
          >
            <Select
              placeholder="选择比对模型"
              options={llms.map(model => ({ label: model.name, value: model.id }))}
            />
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
          <Form.Item
            name="baseline_source"
            label="比较基准"
            rules={[{ required: true, message: '请选择比较基准' }]}
          >
            <Select
              options={[
                { label: '和当前执行比较', value: 'reference_execution' },
                { label: '和场景基线比较', value: 'scenario_baseline' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="llm_model_id"
            label="比对模型"
            rules={[{ required: true, message: '请选择比对模型' }]}
          >
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
