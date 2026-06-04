import { useNavigate } from 'react-router-dom'
import { Layout, Button, Dropdown, Badge, theme, Breadcrumb } from 'antd'
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  UserOutlined,
  LogoutOutlined,
  BellOutlined,
} from '@ant-design/icons'
import { useAdminStore } from '@/store'

const { Header } = Layout

const AppHeader = () => {
  const navigate = useNavigate()
  const { token } = theme.useToken()
  const { user, collapsed, toggleCollapsed, logout } = useAdminStore()

  const handleLogout = () => {
    logout()
    navigate('/admin/login')
  }

  const userMenuItems = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: '个人中心',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      danger: true,
      onClick: handleLogout,
    },
  ]

  return (
    <Header
      style={{
        padding: '0 24px',
        background: token.colorBgContainer,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        boxShadow: '0 1px 4px rgba(0,21,41,0.08)',
        position: 'sticky',
        top: 0,
        zIndex: 99,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <Button
          type="text"
          icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          onClick={toggleCollapsed}
          style={{ fontSize: 16, width: 64, height: 64 }}
        />
        <Breadcrumb
          items={[
            { title: '首页' },
            { title: '管理后台' },
          ]}
        />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <Badge count={5} size="small">
          <Button type="text" icon={<BellOutlined />} style={{ fontSize: 16 }} />
        </Badge>

        <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: '50%',
                background: token.colorPrimary,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
              }}
            >
              {user?.nickname?.[0] || <UserOutlined />}
            </div>
            <span style={{ fontSize: 14 }}>{user?.nickname || '管理员'}</span>
          </div>
        </Dropdown>
      </div>
    </Header>
  )
}

export default AppHeader
