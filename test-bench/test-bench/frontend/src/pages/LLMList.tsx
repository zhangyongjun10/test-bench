import React, { useState, useEffect } from 'react'
import { Table, Button, Space, Input, Modal, Form, message, Popconfirm, Tag } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, ExperimentOutlined, StarOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { LLMModel } from '../api/types'
import { llmApi } from '../api/client'

const LLMList: React.FC = () => {
  const [models, setModels] = useState<LLMModel[]>([])
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [isEdit, setIsEdit] = useState(false)
  const [currentId, setCurrentId] = useState<string>('')
  const [form] = Form.useForm()

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await llmApi.list(keyword || undefined)
      setModels(res.data || [])
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [keyword])

  const handleCreate = () => {
    setIsEdit(false)
    setCurrentId('')
    form.resetFields()
    form.setFieldsValue({ temperature: 0.0, max_tokens: 1024, is_default: false })
    setModalVisible(true)
  }

  const handleEdit = (record: LLMModel) => {
    setIsEdit(true)
    setCurrentId(record.id)
    form.setFieldsValue({
      name: record.name,
      provider: record.provider,
      model_id: record.model_id,
      base_url: record.base_url,
      temperature: record.temperature,
      max_tokens: record.max_tokens,
      is_default: record.is_default,
    })
    setModalVisible(true)
  }

  const handleDelete = async (id: string) => {
    try {
      await llmApi.delete(id)
      message.success('删除成功')
      loadData()
    } catch (e: any) {
      message.error(e.message)
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
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleSetDefault = async (id: string) => {
    try {
      await llmApi.setDefault(id)
      message.success('设置成功')
      loadData()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (isEdit) {
        await llmApi.update(currentId, values)
        message.success('更新成功')
      } else {
        await llmApi.create(values)
        message.success('创建成功')
      }
      setModalVisible(false)
      loadData()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const columns: ColumnsType<LLMModel> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 150,
    },
    {
      title: '提供商',
      dataIndex: 'provider',
      key: 'provider',
      width: 100,
    },
    {
      title: '模型ID',
      dataIndex: 'model_id',
      key: 'model_id',
      width: 150,
    },
    {
      title: '温度',
      dataIndex: 'temperature',
      key: 'temperature',
      width: 80,
    },
    {
      title: '默认',
      dataIndex: 'is_default',
      key: 'is_default',
      width: 80,
      render: (v) => v ? <Tag color="green">默认</Tag> : null,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
    },
    {
      title: '操作',
      key: 'action',
      width: 260,
      fixed: 'right',
      render: (_, record) => (
        <Space size="middle">
          <Button
            type="link"
            size="small"
            icon={<ExperimentOutlined />}
            onClick={() => handleTest(record.id)}
          >
            测试
          </Button>
          {!record.is_default && (
            <Button
              type="link"
              size="small"
              icon={<StarOutlined />}
              onClick={() => handleSetDefault(record.id)}
            >
              默认
            </Button>
          )}
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          {!record.is_default && (
            <Popconfirm title="确认删除吗？" onConfirm={() => handleDelete(record.id)}>
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', gap: 16 }}>
        <Input.Search
          placeholder="搜索模型名称"
          allowClear
          style={{ width: 300 }}
          onSearch={setKeyword}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          添加 LLM 模型
        </Button>
      </div>
      <Table
        columns={columns}
        dataSource={models}
        loading={loading}
        rowKey="id"
        pagination={{ pageSize: 10 }}
      />
      <Modal
        title={isEdit ? '编辑 LLM 模型' : '添加 LLM 模型'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input placeholder="例如: GPT-4" />
          </Form.Item>
          <Form.Item
            name="provider"
            label="提供商"
            rules={[{ required: true, message: '请输入提供商' }]}
          >
            <Input placeholder="例如: openai" />
          </Form.Item>
          <Form.Item
            name="model_id"
            label="模型 ID"
            rules={[{ required: true, message: '请输入模型 ID' }]}
          >
            <Input placeholder="例如: gpt-4" />
          </Form.Item>
          <Form.Item name="base_url" label="API 地址">
            <Input placeholder="例如: https://api.openai.com/v1" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label="API Key"
            rules={[{ required: !isEdit, message: '请输入 API Key' }]}
          >
            <Input.Password placeholder="输入 API Key" />
          </Form.Item>
          <Form.Item
            name="temperature"
            label="Temperature"
            initialValue={0.0}
          >
            <Input type="number" step={0.1} min={0} max={2} />
          </Form.Item>
          <Form.Item
            name="max_tokens"
            label="Max Tokens"
            initialValue={1024}
          >
            <Input type="number" />
          </Form.Item>
          <Form.Item name="is_default" valuePropName="checked" initialValue={false}>
            <div>设置为默认比对模型</div>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default LLMList
