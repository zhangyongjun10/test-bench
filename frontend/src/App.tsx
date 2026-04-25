import { useState } from 'react'
import { Layout, Menu } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  ApiOutlined,
  CloudServerOutlined,
  ClusterOutlined,
  FileTextOutlined,
  PlayCircleOutlined,
  RobotOutlined,
  SettingOutlined,
} from '@ant-design/icons'

const { Header, Sider, Content } = Layout

// 应用壳负责统一左侧导航结构，Case 模块入口文案需要与列表页保持一致，避免跨页认知割裂。
const App = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)

  const aaasMenuItems = [
    { key: '/agents', icon: <RobotOutlined />, label: 'Agent 管理' },
    { key: '/llms', icon: <ApiOutlined />, label: 'LLM 模型' },
    { key: '/scenarios', icon: <FileTextOutlined />, label: 'Case 管理' },
    { key: '/executions', icon: <PlayCircleOutlined />, label: '测试执行' },
    { key: '/system', icon: <SettingOutlined />, label: '系统配置' },
  ]

  const menuItems = [
    {
      key: 'aaas',
      icon: <CloudServerOutlined />,
      label: 'AaaS 平台',
      children: aaasMenuItems,
    },
    {
      key: 'maas',
      icon: <ClusterOutlined />,
      label: 'MaaS 平台',
      children: [],
    },
  ]

  let selectedKey = location.pathname
  if (location.pathname === '/' || location.pathname === '') {
    selectedKey = aaasMenuItems[0].key
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}>
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'white',
            fontSize: collapsed ? 16 : 18,
            fontWeight: 'bold',
          }}
        >
          TestBench
        </div>
        <Menu
          theme="dark"
          selectedKeys={[selectedKey]}
          defaultOpenKeys={['aaas']}
          mode="inline"
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: 0 }} />
        <Content style={{ margin: '16px', minHeight: 280 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}

export default App
