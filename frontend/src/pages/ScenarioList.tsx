import { useEffect, useState } from 'react'
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import type { CSSProperties } from 'react'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { agentApi, scenarioApi } from '../api/client'
import type { Agent, Scenario, ScenarioCreate, ScenarioUpdate } from '../api/types'

const { TextArea } = Input
const { Paragraph, Text, Title } = Typography

const MODAL_SURFACE_STYLE: CSSProperties = {
  padding: 20,
  borderRadius: 20,
  background: '#ffffff',
}

const HEADER_STYLE: CSSProperties = {
  paddingBottom: 16,
  marginBottom: 16,
  borderBottom: '1px solid #e2e8f0',
}

const META_SECTION_STYLE: CSSProperties = {
  padding: 18,
  borderRadius: 18,
  background: '#f8fafc',
  border: '1px solid #e2e8f0',
}

const EDITOR_PANEL_STYLE: CSSProperties = {
  padding: 18,
  borderRadius: 18,
  background: '#fcfdff',
  border: '1px solid #dbe7f3',
}

const CLAMPED_TEXT_STYLE: CSSProperties = {
  marginBottom: 0,
  display: '-webkit-box',
  overflow: 'hidden',
  WebkitLineClamp: 2,
  WebkitBoxOrient: 'vertical',
  whiteSpace: 'pre-wrap',
}

// 统一定义 Case 表单值，创建与编辑都以多 Agent 集合作为唯一归属来源。
type ScenarioFormValues = {
  agent_ids?: string[]
  name: string
  description?: string
  prompt: string
  baseline_result: string
  llm_count_min: number
  llm_count_max: number
  compare_enabled: boolean
}

// 统一按上海时区格式化时间，避免列表与详情页对同一时间出现不同认知。
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

// 列表中的长文本统一压缩为两行预览，同时保留悬浮全文，兼顾信息密度与可读性。
const renderMultilinePreview = (value?: string) => {
  if (!value) {
    return '-'
  }

  return (
    <Paragraph style={CLAMPED_TEXT_STYLE} ellipsis={{ rows: 2, tooltip: value }}>
      {value}
    </Paragraph>
  )
}

// Case 列表页负责 Case 的筛选、录入、编辑和删除，并突出输入 Prompt 与基线输出两个核心字段。
const ScenarioList = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [currentAgentId, setCurrentAgentId] = useState('')
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [isEdit, setIsEdit] = useState(false)
  const [currentId, setCurrentId] = useState('')
  const [form] = Form.useForm<ScenarioFormValues>()

  // Agent 列表既用于筛选也用于编辑表单，因此页面进入时优先加载。
  const loadAgents = async () => {
    try {
      const response = await agentApi.list()
      setAgents(response.data || [])
    } catch (error: any) {
      message.error(error.message)
    }
  }

  // Case 查询根据 Agent 与关键字联动刷新，确保列表始终反映当前筛选条件。
  const loadData = async () => {
    setLoading(true)
    try {
      const response = await scenarioApi.list(currentAgentId || undefined, keyword || undefined)
      setScenarios(response.data || [])
    } catch (error: any) {
      message.error(error.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadAgents()
  }, [])

  useEffect(() => {
    void loadData()
  }, [currentAgentId, keyword])

  // 新建 Case 时预置多 Agent 选择与比对范围，避免空值影响后续执行规则。
  const openCreateModal = () => {
    setIsEdit(false)
    setCurrentId('')
    form.resetFields()
    form.setFieldsValue({
      agent_ids: [],
      llm_count_min: 0,
      llm_count_max: 999,
      compare_enabled: true,
    })
    setModalVisible(true)
  }

  // 编辑 Case 时回填同一条记录的多 Agent 集合，保证归属信息与当前存储一致。
  const openEditModal = (record: Scenario) => {
    setIsEdit(true)
    setCurrentId(record.id)
    form.setFieldsValue({
      agent_ids: record.agent_ids,
      name: record.name,
      description: record.description,
      prompt: record.prompt,
      baseline_result: record.baseline_result || '',
      llm_count_min: record.llm_count_min,
      llm_count_max: record.llm_count_max,
      compare_enabled: record.compare_enabled,
    })
    setModalVisible(true)
  }

  // 删除成功后立即刷新列表，避免继续在旧数据上操作。
  const handleDelete = async (id: string) => {
    try {
      await scenarioApi.delete(id)
      message.success('删除成功')
      await loadData()
    } catch (error: any) {
      message.error(error.message)
    }
  }

  // 提交时统一走单条 Case 的保存逻辑，创建与编辑都整组回写 Agent 关联集合。
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const payload: ScenarioCreate | ScenarioUpdate = {
        agent_ids: values.agent_ids,
        name: values.name,
        description: values.description,
        prompt: values.prompt,
        baseline_result: values.baseline_result,
        llm_count_min: values.llm_count_min,
        llm_count_max: values.llm_count_max,
        compare_enabled: values.compare_enabled,
      }

      if (isEdit) {
        await scenarioApi.update(currentId, payload)
        message.success('更新成功')
      } else {
        await scenarioApi.create(payload as ScenarioCreate)
        message.success('创建成功')
      }
      setModalVisible(false)
      await loadData()
    } catch (error: any) {
      if (error?.errorFields) {
        return
      }
      message.error(error.message)
    }
  }

  // 列表字段聚焦可直接用于测试核对的信息，展示单条 Case 对应的多个 Agent。
  const columns: ColumnsType<Scenario> = [
    {
      title: 'Case 名称',
      dataIndex: 'name',
      key: 'name',
      width: 220,
      render: value => <Text strong>{value}</Text>,
    },
    {
      title: '所属 Agent',
      dataIndex: 'agent_names',
      key: 'agent_names',
      width: 240,
      render: (value?: string[]) =>
        value && value.length > 0 ? (
          <Space size={[4, 8]} wrap>
            {value.map(agentName => (
              <Tag key={agentName} color="blue">
                {agentName}
              </Tag>
            ))}
          </Space>
        ) : (
          '-'
        ),
    },
    {
      title: '输入 Prompt',
      dataIndex: 'prompt',
      key: 'prompt',
      width: 320,
      render: value => renderMultilinePreview(value),
    },
    {
      title: '基线输出',
      dataIndex: 'baseline_result',
      key: 'baseline_result',
      width: 320,
      render: value => renderMultilinePreview(value),
    },
    {
      title: 'LLM 调用范围',
      key: 'llm_count_range',
      width: 160,
      render: (_, record) => `${record.llm_count_min} ~ ${record.llm_count_max}`,
    },
    {
      title: '自动比对',
      dataIndex: 'compare_enabled',
      key: 'compare_enabled',
      width: 110,
      render: value => <Tag color={value ? 'green' : 'default'}>{value ? '启用' : '关闭'}</Tag>,
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
      width: 160,
      fixed: 'right',
      render: (_, record) => (
        <Space size="middle">
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确认删除这个 Case 吗？" onConfirm={() => void handleDelete(record.id)}>
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
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <Select
          placeholder="选择 Agent"
          style={{ width: 220 }}
          allowClear
          value={currentAgentId || undefined}
          onChange={value => setCurrentAgentId(value || '')}
          options={agents.map(agent => ({ label: agent.name, value: agent.id }))}
        />
        <Input.Search
          placeholder="搜索 Case 名称"
          allowClear
          style={{ width: 280 }}
          onSearch={value => setKeyword(value.trim())}
          onChange={event => {
            if (!event.target.value) {
              setKeyword('')
            }
          }}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
          添加 Case
        </Button>
      </div>

      <Table
        columns={columns}
        dataSource={scenarios}
        loading={loading}
        rowKey="id"
        scroll={{ x: 1700 }}
        pagination={{ pageSize: 10 }}
      />

      <Modal
        title={null}
        open={modalVisible}
        onOk={() => void handleSubmit()}
        onCancel={() => setModalVisible(false)}
        width={1080}
        okText={isEdit ? '保存 Case' : '创建 Case'}
        cancelText="取消"
        styles={{ body: { padding: 24, background: '#f8fafc' } }}
      >
        <div style={MODAL_SURFACE_STYLE}>
          <div style={HEADER_STYLE}>
            <Title level={3} style={{ margin: 0, color: '#0f172a' }}>
              {isEdit ? '编辑 Case' : '添加 Case'}
            </Title>
          </div>

          <Form form={form} layout="vertical">
            <div style={META_SECTION_STYLE}>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                  gap: 16,
                  marginBottom: 8,
                }}
              >
                <Form.Item
                  name="agent_ids"
                  label="所属 Agent"
                  extra="支持多选；同一条 Case 会被这些 Agent 共同复用。"
                  rules={[{ required: true, message: '请至少选择一个 Agent' }]}
                >
                  <Select
                    mode="multiple"
                    placeholder="选择一个或多个 Agent"
                    options={agents.map(agent => ({ label: agent.name, value: agent.id }))}
                  />
                </Form.Item>

                <Form.Item
                  name="name"
                  label="Case 名称"
                  rules={[{ required: true, message: '请输入 Case 名称' }]}
                >
                  <Input placeholder="例如：客服退款政策问答" />
                </Form.Item>
              </div>

              <Form.Item name="description" label="备注说明" style={{ marginBottom: 0 }}>
                <TextArea
                  rows={4}
                  placeholder="可选，用于补充这个 Case 的测试目标或边界条件"
                  style={{ minHeight: 112, resize: 'vertical' }}
                />
              </Form.Item>
            </div>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))',
                gap: 16,
                marginTop: 16,
                marginBottom: 16,
                alignItems: 'stretch',
              }}
            >
              <div style={EDITOR_PANEL_STYLE}>
                <Form.Item
                  name="prompt"
                  label="输入 Prompt"
                  extra="这里填写实际发送给 Agent 的输入内容。"
                  rules={[{ required: true, message: '请输入输入 Prompt' }]}
                  style={{ marginBottom: 0 }}
                >
                  <TextArea
                    rows={16}
                    showCount
                    placeholder="输入发送给 Agent 的问题、指令或完整测试上下文"
                    style={{ minHeight: 340, resize: 'vertical' }}
                  />
                </Form.Item>
              </div>

              <div style={EDITOR_PANEL_STYLE}>
                <Form.Item
                  name="baseline_result"
                  label="基线输出"
                  extra="必填，用于执行后最终输出的一致性判定。"
                  rules={[{ required: true, message: '请输入基线输出' }]}
                  style={{ marginBottom: 0 }}
                >
                  <TextArea
                    rows={16}
                    showCount
                    placeholder="填写预期的标准输出或参考答案"
                    style={{ minHeight: 340, resize: 'vertical' }}
                  />
                </Form.Item>
              </div>
            </div>

            <div style={META_SECTION_STYLE}>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                  gap: 16,
                }}
              >
                <Form.Item
                  name="llm_count_min"
                  label="LLM 最小调用次数"
                  rules={[{ required: true, message: '请输入最小次数' }]}
                >
                  <InputNumber min={0} precision={0} style={{ width: '100%' }} />
                </Form.Item>

                <Form.Item
                  name="llm_count_max"
                  label="LLM 最大调用次数"
                  dependencies={['llm_count_min']}
                  rules={[
                    { required: true, message: '请输入最大次数' },
                    ({ getFieldValue }) => ({
                      validator(_, value: number | undefined) {
                        const minValue = getFieldValue('llm_count_min')
                        if (value == null || minValue == null || value >= minValue) {
                          return Promise.resolve()
                        }
                        return Promise.reject(new Error('最大次数不能小于最小次数'))
                      },
                    }),
                  ]}
                >
                  <InputNumber min={0} precision={0} style={{ width: '100%' }} />
                </Form.Item>

                <Form.Item
                  name="compare_enabled"
                  label="启用自动比对"
                  valuePropName="checked"
                  initialValue
                >
                  <Switch />
                </Form.Item>
              </div>
            </div>
          </Form>
        </div>
      </Modal>
    </div>
  )
}

export default ScenarioList
