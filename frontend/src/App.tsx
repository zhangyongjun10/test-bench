import { useState } from 'react'
import { Layout, Menu } from 'antd'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import {
  RobotOutlined,
  ApiOutlined,
  FileTextOutlined,
  PlayCircleOutlined,
  SettingOutlined,
  CloudServerOutlined,
  ClusterOutlined,
} from '@ant-design/icons'

const { Header, Sider, Content } = Layout

const App = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)

  const aaasMenuItems = [
    { key: '/agents', icon: <RobotOutlined />, label: 'Agent 管理' },
    { key: '/llms', icon: <ApiOutlined />, label: 'LLM 模型' },
    { key: '/scenarios', icon: <FileTextOutlined />, label: '测试场景' },
    { key: '/executions', icon: <PlayCircleOutlined />, label: '测试执行' },
    { key: '/system', icon: <SettingOutlined />, label: '系统配置' },
  ]

  const menuItems = [
    {
      key: 'aaas',
      icon: <CloudServerOutlined />,
      label: 'AaaS平台',
      children: aaasMenuItems,
    },
    {
      key: 'maas',
      icon: <ClusterOutlined />,
      label: 'MaaS平台',
      children: [],
    },
  ]

  // 默认展开 AaaS 平台

  // 默认选中第一个菜单项（Agent 管理）当路径为根路径或没有匹配时
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
