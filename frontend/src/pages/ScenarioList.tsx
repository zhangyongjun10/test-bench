import React, { useState, useEffect } from 'react'
import { Table, Button, Space, Input, Modal, Form, message, Popconfirm, Select } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { Scenario, Agent } from '../api/types'
import { scenarioApi } from '../api/client'
import { agentApi } from '../api/client'

const ScenarioList: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [currentAgentId, setCurrentAgentId] = useState<string>('')
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [isEdit, setIsEdit] = useState(false)
  const [currentId, setCurrentId] = useState<string>('')
  const [form] = Form.useForm()

  const loadAgents = async () => {
    try {
      const res = await agentApi.list()
      setAgents(res.data || [])
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await scenarioApi.list(currentAgentId || undefined, keyword || undefined)
      setScenarios(res.data || [])
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAgents()
    loadData()
  }, [])

  useEffect(() => {
    loadData()
  }, [currentAgentId, keyword])

  const handleCreate = () => {
    setIsEdit(false)
    setCurrentId('')
    form.resetFields()
    form.setFieldsValue({ compare_result: true, compare_process: false })
    setModalVisible(true)
  }

  const handleEdit = (record: Scenario) => {
    setIsEdit(true)
    setCurrentId(record.id)
    form.setFieldsValue({
      agent_id: record.agent_id,
      name: record.name,
      description: record.description,
      prompt: record.prompt,
      baseline_result: record.baseline_result,
      compare_result: record.compare_result,
      compare_process: record.compare_process,
    })
    setModalVisible(true)
  }

  const handleDelete = async (id: string) => {
    try {
      await scenarioApi.delete(id)
      message.success('删除成功')
      loadData()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (isEdit) {
        await scenarioApi.update(currentId, values)
        message.success('更新成功')
      } else {
        await scenarioApi.create(values)
        message.success('创建成功')
      }
      setModalVisible(false)
      loadData()
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const columns: ColumnsType<Scenario> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 180,
    },
    {
      title: '所属 Agent',
      dataIndex: 'agent_name',
      key: 'agent_name',
      width: 150,
      render: text => text || '-',
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
    },
    {
      title: '比对结果',
      dataIndex: 'compare_result',
      key: 'compare_result',
      width: 100,
      render: v => v ? '是' : '否',
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
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
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
          placeholder="选择 Agent"
          style={{ width: 200 }}
          allowClear
          value={currentAgentId || undefined}
          onChange={setCurrentAgentId}
          options={agents.map(a => ({ label: a.name, value: a.id }))}
        />
        <Input.Search
          placeholder="搜索场景名称"
          allowClear
          style={{ width: 250 }}
          onSearch={setKeyword}
        />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleCreate}
        >
          添加场景
        </Button>
      </div>
      <Table
        columns={columns}
        dataSource={scenarios}
        loading={loading}
        rowKey="id"
        pagination={{ pageSize: 10 }}
      />
      <Modal
        title={isEdit ? '编辑场景' : '添加场景'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={700}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="agent_id"
            label="所属 Agent"
            rules={[{ required: true, message: '请选择 Agent' }]}
          >
            <Select placeholder="选择 Agent" options={agents.map(a => ({ label: a.name, value: a.id }))} />
          </Form.Item>
          <Form.Item
            name="name"
            label="场景名称"
            rules={[{ required: true, message: '请输入场景名称' }]}
          >
            <Input placeholder="例如: 客服问答测试" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="描述这个场景测试的内容" rows={2} />
          </Form.Item>
          <Form.Item
            name="prompt"
            label="基准问题/提示词"
            rules={[{ required: true, message: '请输入基准提示词' }]}
          >
            <Input.TextArea placeholder="输入给 Agent 的问题/提示词" rows={4} />
          </Form.Item>
          <Form.Item name="baseline_result" label="基准预期结果">
            <Input.TextArea placeholder="输入预期的输出结果，用于比对" rows={6} />
          </Form.Item>
          <Form.Item
            name="compare_result"
            valuePropName="checked"
            initialValue={true}
          >
            <div>比对输出结果</div>
          </Form.Item>
          <Form.Item
            name="compare_process"
            valuePropName="checked"
            initialValue={false}
          >
            <div>比对执行过程</div>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ScenarioList
