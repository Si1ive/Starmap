import { Outlet } from 'react-router-dom'
import { Layout as AntLayout } from 'antd'
import AppHeader from '../Header'
import AppSider from '../Sider'
import { useAdminStore } from '@/store'

const { Content } = AntLayout

const Layout = () => {
  const { collapsed } = useAdminStore()

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <AppSider />
      <AntLayout style={{ marginLeft: collapsed ? 80 : 200, transition: 'margin-left 0.2s' }}>
        <AppHeader />
        <Content
          style={{
            margin: '24px 16px',
            padding: 24,
            minHeight: 280,
            background: '#fff',
            borderRadius: 8,
          }}
        >
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  )
}

export default Layout
