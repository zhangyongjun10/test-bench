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
  message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { agentApi, scenarioApi } from '../api/client'
import type { Agent, Scenario } from '../api/types'

const { TextArea } = Input

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

const ScenarioList = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [currentAgentId, setCurrentAgentId] = useState<string>("")
  const [keyword, setKeyword] = useState("")
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [isEdit, setIsEdit] = useState(false)
  const [currentId, setCurrentId] = useState("")
  const [form] = Form.useForm()

  const loadAgents = async () => {
    try {
      const res = await agentApi.list()
      setAgents(res.data || [])
    } catch (error: any) {
      message.error(error.message)
    }
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await scenarioApi.list(currentAgentId || undefined, keyword || undefined)
      setScenarios(res.data || [])
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

  const openCreateModal = () => {
    setIsEdit(false)
    setCurrentId("")
    form.resetFields()
    form.setFieldsValue({
      llm_count_min: 0,
      llm_count_max: 999,
      compare_enabled: true,
    })
    setModalVisible(true)
  }

  const openEditModal = (record: Scenario) => {
    setIsEdit(true)
    setCurrentId(record.id)
    form.setFieldsValue({
      agent_id: record.agent_id,
      name: record.name,
      description: record.description,
      prompt: record.prompt,
      baseline_result: record.baseline_result,
      llm_count_min: record.llm_count_min,
      llm_count_max: record.llm_count_max,
      compare_enabled: record.compare_enabled,
    })
    setModalVisible(true)
  }

  const handleDelete = async (id: string) => {
    try {
      await scenarioApi.delete(id)
      message.success("删除成功")
      await loadData()
    } catch (error: any) {
      message.error(error.message)
    }
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (isEdit) {
        await scenarioApi.update(currentId, values)
        message.success("更新成功")
      } else {
        await scenarioApi.create(values)
        message.success("创建成功")
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

  const columns: ColumnsType<Scenario> = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      width: 180,
    },
    {
      title: "所属 Agent",
      dataIndex: "agent_name",
      key: "agent_name",
      width: 160,
      render: value => value || "-",
    },
    {
      title: "LLM 调用范围",
      key: "llm_count_range",
      width: 160,
      render: (_, record) => `${record.llm_count_min} ~ ${record.llm_count_max}`,
    },
    {
      title: "自动比对",
      dataIndex: "compare_enabled",
      key: "compare_enabled",
      width: 110,
      render: value => (
        <Tag color={value ? "green" : "default"}>{value ? "启用" : "关闭"}</Tag>
      ),
    },
    {
      title: "描述",
      dataIndex: "description",
      key: "description",
      render: value => value || "-",
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: formatLocalTime,
    },
    {
      title: "操作",
      key: "action",
      width: 140,
      fixed: "right",
      render: (_, record) => (
        <Space size="middle">
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确认删除这个场景吗？" onConfirm={() => void handleDelete(record.id)}>
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
      <div style={{ marginBottom: 16, display: "flex", gap: 16, alignItems: "center" }}>
        <Select
          placeholder="选择 Agent"
          style={{ width: 220 }}
          allowClear
          value={currentAgentId || undefined}
          onChange={value => setCurrentAgentId(value || "")}
          options={agents.map(agent => ({ label: agent.name, value: agent.id }))}
        />
        <Input.Search
          placeholder="搜索场景名称"
          allowClear
          style={{ width: 260 }}
          onSearch={value => setKeyword(value)}
          onChange={event => {
            if (!event.target.value) {
              setKeyword("")
            }
          }}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
          添加场景
        </Button>
      </div>

      <Table columns={columns} dataSource={scenarios} loading={loading} rowKey="id" pagination={{ pageSize: 10 }} />

      <Modal
        title={isEdit ? "编辑场景" : "添加场景"}
        open={modalVisible}
        onOk={() => void handleSubmit()}
        onCancel={() => setModalVisible(false)}
        width={720}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="agent_id"
            label="所属 Agent"
            rules={[{ required: true, message: "请选择 Agent" }]}
          >
            <Select
              placeholder="选择 Agent"
              options={agents.map(agent => ({ label: agent.name, value: agent.id }))}
            />
          </Form.Item>

          <Form.Item
            name="name"
            label="场景名称"
            rules={[{ required: true, message: "请输入场景名称" }]}
          >
            <Input placeholder="例如：客服问答测试" />
          </Form.Item>

          <Form.Item name="description" label="描述">
            <TextArea rows={2} placeholder="描述这个场景的测试目标" />
          </Form.Item>

          <Form.Item
            name="prompt"
            label="测试 Prompt"
            rules={[{ required: true, message: "请输入测试 Prompt" }]}
          >
            <TextArea rows={4} placeholder="输入发送给 Agent 的问题或提示词" />
          </Form.Item>

          <Form.Item name="baseline_result" label="基线输出">
            <TextArea rows={6} placeholder="可选。用于最终输出一致性判断。" />
          </Form.Item>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Form.Item
              name="llm_count_min"
              label="LLM 最小调用次数"
              rules={[{ required: true, message: "请输入最小次数" }]}
            >
              <InputNumber min={0} precision={0} style={{ width: "100%" }} />
            </Form.Item>

            <Form.Item
              name="llm_count_max"
              label="LLM 最大调用次数"
              dependencies={["llm_count_min"]}
              rules={[
                { required: true, message: "请输入最大次数" },
                ({ getFieldValue }) => ({
                  validator(_, value: number | undefined) {
                    const minValue = getFieldValue("llm_count_min")
                    if (value == null || minValue == null || value >= minValue) {
                      return Promise.resolve()
                    }
                    return Promise.reject(new Error("最大次数不能小于最小次数"))
                  },
                }),
              ]}
            >
              <InputNumber min={0} precision={0} style={{ width: "100%" }} />
            </Form.Item>
          </div>

          <Form.Item
            name="compare_enabled"
            label="启用自动比对"
            valuePropName="checked"
            initialValue
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ScenarioList
