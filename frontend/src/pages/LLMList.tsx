import { useEffect, useState } from 'react'
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Space,
  Table,
  message,
} from 'antd'
import { DeleteOutlined, EditOutlined, ExperimentOutlined, PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { llmApi } from '../api/client'
import type { LLMModel } from '../api/types'

const { TextArea } = Input

const DEFAULT_COMPARISON_PROMPT = `请判断下面【基线输出】和【实际输出】的核心语义是否一致：

基线输出:
{{baseline_result}}

实际输出:
{{actual_result}}

要求：
1. 核心语义一致（回答结论相同、解决同一个问题、满足相同需求）时返回 consistent = true
2. 核心语义不一致时返回 consistent = false
3. 简要说明判断原因
4. 只输出 JSON：{"consistent": boolean, "reason": string}`

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

const LLMList = () => {
  const [models, setModels] = useState<LLMModel[]>([])
  const [keyword, setKeyword] = useState("")
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [isEdit, setIsEdit] = useState(false)
  const [currentId, setCurrentId] = useState("")
  const [form] = Form.useForm()

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await llmApi.list(keyword || undefined)
      setModels(res.data || [])
    } catch (error: any) {
      message.error(error.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [keyword])

  const openCreateModal = () => {
    setIsEdit(false)
    setCurrentId("")
    form.resetFields()
    form.setFieldsValue({
      temperature: 0,
      max_tokens: 1024,
      comparison_prompt: DEFAULT_COMPARISON_PROMPT,
    })
    setModalVisible(true)
  }

  const openEditModal = (record: LLMModel) => {
    setIsEdit(true)
    setCurrentId(record.id)
    form.setFieldsValue({
      name: record.name,
      provider: record.provider,
      model_id: record.model_id,
      base_url: record.base_url,
      temperature: record.temperature,
      max_tokens: record.max_tokens,
      comparison_prompt: record.comparison_prompt || DEFAULT_COMPARISON_PROMPT,
    })
    setModalVisible(true)
  }

  const handleDelete = async (id: string) => {
    try {
      await llmApi.delete(id)
      message.success("删除成功")
      await loadData()
    } catch (error: any) {
      message.error(error.message)
    }
  }

  const handleTest = async (id: string) => {
    try {
      const res = await llmApi.test(id)
      if (res.data.success) {
        message.success(res.data.message)
      } else {
        message.error(res.data.message)
      }
    } catch (error: any) {
      message.error(error.message)
    }
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (isEdit) {
        await llmApi.update(currentId, values)
        message.success("更新成功")
      } else {
        await llmApi.create(values)
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

  const columns: ColumnsType<LLMModel> = [
    { title: "名称", dataIndex: "name", key: "name", width: 180 },
    { title: "提供商", dataIndex: "provider", key: "provider", width: 120 },
    { title: "模型 ID", dataIndex: "model_id", key: "model_id", width: 220 },
    { title: "Temperature", dataIndex: "temperature", key: "temperature", width: 110 },
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
      width: 220,
      fixed: "right",
      render: (_, record) => (
        <Space size="middle">
          <Button type="link" size="small" icon={<ExperimentOutlined />} onClick={() => void handleTest(record.id)}>
            测试
          </Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确认删除这个模型吗？" onConfirm={() => void handleDelete(record.id)}>
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
      <div style={{ marginBottom: 16, display: "flex", gap: 16 }}>
        <Input.Search
          placeholder="搜索模型名称"
          allowClear
          style={{ width: 320 }}
          onSearch={value => setKeyword(value)}
          onChange={event => {
            if (!event.target.value) {
              setKeyword("")
            }
          }}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
          添加 LLM 模型
        </Button>
      </div>

      <Table columns={columns} dataSource={models} loading={loading} rowKey="id" pagination={{ pageSize: 10 }} />

      <Modal
        title={isEdit ? "编辑 LLM 模型" : "添加 LLM 模型"}
        open={modalVisible}
        onOk={() => void handleSubmit()}
        onCancel={() => setModalVisible(false)}
        width={760}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input placeholder="例如：GPT-4o Compare" />
          </Form.Item>

          <Form.Item name="provider" label="提供商" rules={[{ required: true, message: "请输入提供商" }]}>
            <Input placeholder="例如：openai" />
          </Form.Item>

          <Form.Item name="model_id" label="模型 ID" rules={[{ required: true, message: "请输入模型 ID" }]}>
            <Input placeholder="例如：gpt-4o" />
          </Form.Item>

          <Form.Item name="base_url" label="API 地址">
            <Input placeholder="例如：https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item
            name="api_key"
            label="API Key"
            rules={[{ required: !isEdit, message: "请输入 API Key" }]}
          >
            <Input.Password placeholder={isEdit ? "留空表示不修改" : "输入 API Key"} />
          </Form.Item>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Form.Item name="temperature" label="Temperature" initialValue={0}>
              <InputNumber min={0} max={2} step={0.1} style={{ width: "100%" }} />
            </Form.Item>

            <Form.Item name="max_tokens" label="Max Tokens" initialValue={1024}>
              <InputNumber min={1} step={1} style={{ width: "100%" }} />
            </Form.Item>
          </div>

          <Form.Item
            name="comparison_prompt"
            label="比对 Prompt"
            rules={[{ required: true, message: "请输入比对 Prompt" }]}
          >
            <TextArea rows={10} placeholder="用于最终输出一致性判断的 Prompt 模板" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default LLMList
