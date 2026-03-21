import React, { useState, useEffect } from 'react'
import { Table, Button, Space, Input, Modal, Form, message, Popconfirm, Tag, Select } from 'antd'
import { PlusOutlined, EyeOutlined, DeleteOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import type { ExecutionJob, Agent, Scenario } from '../api/types'
import { executionApi } from '../api/client'
import { agentApi } from '../api/client'
import { scenarioApi } from '../api/client'
import { llmApi } from '../api/client'

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

const ExecutionList: React.FC = () => {
  const navigate = useNavigate()
  const [executions, setExecutions] = useState<ExecutionJob[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [filteredScenarios, setFilteredScenarios] = useState<Scenario[]>([])
  const [modalScenarios, setModalScenarios] = useState<Scenario[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState<string>('')
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [form] = Form.useForm()
  const [llms, setLlms] = useState<any[]>([])

  const loadAgents = async () => {
    try {
      const res = await agentApi.list()
      setAgents(res.data || [])
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const loadLlms = async () => {
    try {
      const res = await llmApi.list()
      setLlms(res.data || [])
    } catch (e: any) {
      message.error('加载模型列表失败: ' + e.message)
    }
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await executionApi.list(
        selectedAgentId || undefined,
        selectedScenarioId || undefined,
        20,
        0
      )
      setExecutions(res.data.items || [])
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  const loadScenariosByAgent = async (agentId: string) => {
    if (!agentId) {
      setFilteredScenarios([])
      setModalScenarios([])
      return
    }
    try {
      const res = await scenarioApi.list(agentId)
      setFilteredScenarios(res.data || [])
      setModalScenarios(res.data || [])
    } catch (e: any) {
      message.error(e.message)
      setFilteredScenarios([])
      setModalScenarios([])
    }
  }

  useEffect(() => {
    loadAgents()
    loadLlms()
    loadData()
  }, [])

  const handleAgentChange = async (agentId: string) => {
    setSelectedAgentId(agentId)
    await loadScenariosByAgent(agentId)
  }

  const handleCreate = () => {
    form.resetFields()
    setModalScenarios([])
    setModalVisible(true)
    // Ensure LLMs are loaded
    if (llms.length === 0) {
      loadLlms()
    }
  }

  const handleModalAgentChange = async (agentId: string) => {
    await loadScenariosByAgent(agentId)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      await executionApi.create(values)
      message.success('执行已触发')
      setModalVisible(false)
      loadData()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await executionApi.delete(id)
      message.success('删除成功')
      loadData()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const columns: ColumnsType<ExecutionJob> = [
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: s => <Tag color={STATUS_COLORS[s] || 'gray'}>{STATUS_TEXT[s] || s}</Tag>,
    },
    {
      title: '比对分数',
      dataIndex: 'comparison_score',
      key: 'comparison_score',
      width: 100,
      render: v => v?.toFixed(2),
    },
    {
      title: '比对结果',
      dataIndex: 'comparison_passed',
      key: 'comparison_passed',
      width: 80,
      render: v =>
        v === true ? (
          <Tag color="green">通过</Tag>
        ) : v === false ? (
          <Tag color="red">不通过</Tag>
        ) : null,
    },
    {
      title: '耗时',
      key: 'duration',
      width: 100,
      render: (_, record) => {
        if (!record.started_at || !record.completed_at) return '-'
        return `${(new Date(record.completed_at).getTime() - new Date(record.started_at).getTime()) / 1000}s`
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (text: string) => {
        // 后端存储的是 UTC 时间，转换为北京时间 (+8)
        const d = new Date(text)
        return new Date(d.getTime() + 8 * 60 * 60 * 1000).toLocaleString('zh-CN')
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      fixed: 'right',
      render: (_, record) => (
        <Space size="middle">
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/execution/${record.id}`)}
          >
            详情
          </Button>
          <Popconfirm title="确认删除吗？" onConfirm={() => handleDelete(record.id)}>
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
          style={{ width: 200 }}
          allowClear
          value={selectedAgentId || undefined}
          onChange={handleAgentChange}
          options={agents.map(a => ({ label: a.name, value: a.id }))}
        />
        <Select
          placeholder="筛选场景"
          style={{ width: 200 }}
          allowClear
          value={selectedScenarioId || undefined}
          onChange={setSelectedScenarioId}
          options={filteredScenarios.map(s => ({ label: s.name, value: s.id }))}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          触发执行
        </Button>
      </div>
      <Table
        columns={columns}
        dataSource={executions}
        loading={loading}
        rowKey="id"
        pagination={{ pageSize: 10 }}
      />
      <Modal
        title="触发新执行"
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="agent_id"
            label="Agent"
            rules={[{ required: true, message: '请选择 Agent' }]}
          >
            <Select
              placeholder="选择 Agent"
              options={agents.map(a => ({ label: a.name, value: a.id }))}
              onChange={handleModalAgentChange}
            />
          </Form.Item>
          <Form.Item
            name="scenario_id"
            label="测试场景"
            rules={[{ required: true, message: '请选择场景' }]}
          >
            <Select
              placeholder="选择场景"
              options={modalScenarios.map(s => ({ label: s.name, value: s.id }))}
            />
          </Form.Item>
          <Form.Item name="llm_model_id" label="比对模型（默认使用默认模型）">
            <Select
              placeholder="选择比对模型"
              options={llms.map(l => ({ label: l.name, value: l.id }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ExecutionList
