import { Layout, Menu } from 'antd'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import {
  RobotOutlined,
  ApiOutlined,
  FileTextOutlined,
  PlayCircleOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import React from 'react'

const { Header, Sider, Content } = Layout

const App: React.FC = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = React.useState(false)

  const menuItems = [
    { key: '/agents', icon: <RobotOutlined />, label: 'Agent 管理' },
    { key: '/llms', icon: <ApiOutlined />, label: 'LLM 模型' },
    { key: '/scenarios', icon: <FileTextOutlined />, label: '测试场景' },
    { key: '/executions', icon: <PlayCircleOutlined />, label: '测试执行' },
    { key: '/system', icon: <SettingOutlined />, label: '系统配置' },
  ]

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
          selectedKeys={[location.pathname]}
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
