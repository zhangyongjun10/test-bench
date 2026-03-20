import React, { useState, useEffect } from 'react'
import { Card, Form, Input, Button, message, Radio, Space } from 'antd'
import { ExperimentOutlined } from '@ant-design/icons'
import type { ClickHouseConfig, ClickHouseConfigUpdate, TestResponse } from '../api/types'
import { systemApi } from '../api/client'

const SystemConfig: React.FC = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [testLoading, setTestLoading] = useState(false)
  const [initialLoaded, setInitialLoaded] = useState(false)

  const loadData = async () => {
    try {
      const res = await systemApi.getClickhouse()
      if (res.data) {
        form.setFieldsValue(res.data)
      }
      setInitialLoaded(true)
    } catch (e: any) {
      // 404 是正常的，还没配置
      setInitialLoaded(true)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleSubmit = async (values: ClickHouseConfigUpdate) => {
    setLoading(true)
    try {
      await systemApi.updateClickhouse(values)
      message.success('配置更新成功')
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleTest = async () => {
    const values = form.getFieldsValue()
    setTestLoading(true)
    try {
      const res = await systemApi.testClickhouse(values)
      const data: TestResponse = res.data
      if (data.success) {
        message.success(data.message)
      } else {
        message.error(data.message)
      }
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setTestLoading(false)
    }
  }

  return (
    <Card title="ClickHouse 配置（Opik/Langfuse）">
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        style={{ maxWidth: 600 }}
      >
        <Form.Item
          name="endpoint"
          label="连接地址"
          rules={[{ required: true, message: '请输入 ClickHouse 连接地址' }]}
        >
          <Input placeholder="例如: clickhouse:9000 或者 192.168.1.100:9000" />
        </Form.Item>
        <Form.Item
          name="database"
          label="数据库名"
          rules={[{ required: true, message: '请输入数据库名' }]}
          initialValue="opik"
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="username"
          label="用户名"
          initialValue="default"
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="password"
          label="密码"
        >
          <Input.Password placeholder="如果不需要密码可以留空" />
        </Form.Item>
        <Form.Item
          name="source_type"
          label="数据源类型"
          rules={[{ required: true, message: '请选择数据源类型' }]}
          initialValue="opik"
        >
          <Radio.Group>
            <Radio value="opik">Opik</Radio>
            <Radio value="langfuse">Langfuse</Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={loading}>
              保存配置
            </Button>
            <Button
              icon={<ExperimentOutlined />}
              onClick={handleTest}
              loading={testLoading}
            >
              测试连接
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  )
}

export default SystemConfig
