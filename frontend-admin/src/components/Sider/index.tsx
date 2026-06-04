import { useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu } from 'antd'
import {
  DashboardOutlined,
  UserOutlined,
  VideoCameraOutlined,
  BugOutlined,
  MessageOutlined,
  MonitorOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useAdminStore } from '@/store'

const { Sider } = Layout

const menuItems = [
  { key: '/admin/dashboard', icon: <DashboardOutlined />, label: '数据看板' },
  { key: '/admin/persons', icon: <UserOutlined />, label: '艺人管理' },
  { key: '/admin/works', icon: <VideoCameraOutlined />, label: '作品管理' },
  { key: '/admin/crawler', icon: <BugOutlined />, label: '爬虫管理' },
  { key: '/admin/conversations', icon: <MessageOutlined />, label: '对话管理' },
  { key: '/admin/monitor', icon: <MonitorOutlined />, label: '系统监控' },
  { key: '/admin/settings', icon: <SettingOutlined />, label: '系统配置' },
]

const AppSider = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const { collapsed, permissions } = useAdminStore()

  // 根据权限过滤菜单
  const filteredItems = menuItems.filter((item) => {
    if (item.key === '/admin/settings') {
      return permissions.includes('settings:manage')
    }
    return true
  })

  return (
    <Sider
      trigger={null}
      collapsible
      collapsed={collapsed}
      style={{
        overflow: 'auto',
        height: '100vh',
        position: 'fixed',
        left: 0,
        top: 0,
        bottom: 0,
        zIndex: 100,
      }}
    >
      <div
        style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontSize: collapsed ? 16 : 20,
          fontWeight: 'bold',
          borderBottom: '1px solid rgba(255,255,255,0.1)',
        }}
      >
        {collapsed ? 'SM' : 'StarMap Admin'}
      </div>
      <Menu
        theme="dark"
        mode="inline"
        selectedKeys={[location.pathname]}
        items={filteredItems}
        onClick={({ key }) => navigate(key)}
        style={{ borderRight: 0 }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: 0,
          width: '100%',
          padding: '16px',
          color: 'rgba(255,255,255,0.45)',
          fontSize: 12,
          textAlign: 'center',
          borderTop: '1px solid rgba(255,255,255,0.1)',
        }}
      >
        {collapsed ? '©' : '© 2026 StarMap'}
      </div>
    </Sider>
  )
}

export default AppSider
