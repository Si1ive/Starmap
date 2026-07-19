import { Outlet } from 'react-router-dom'
import { Layout as AntLayout } from 'antd'
import AppHeader from '../Header'
import AppSider from '../Sider'
import { useAdminStore } from '@/store'

const { Content } = AntLayout

const Layout = () => {
  const { collapsed } = useAdminStore()

  return (
    <AntLayout className="admin-shell">
      <AppSider />
      <AntLayout
        className={`admin-shell__column ${collapsed ? 'admin-shell__column--collapsed' : ''}`}
      >
        <AppHeader />
        <Content className="admin-content">
          <div className="admin-content__inner">
            <Outlet />
          </div>
        </Content>
      </AntLayout>
    </AntLayout>
  )
}

export default Layout
