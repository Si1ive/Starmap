import { Outlet } from 'react-router-dom'
import { Layout as AntLayout } from 'antd'
import { useEffect, useState } from 'react'
import AppHeader from '../Header'
import AppSider from '../Sider'
import { useAdminStore } from '@/store'

const { Content } = AntLayout

const Layout = () => {
  const { collapsed, setCollapsed } = useAdminStore()
  const [isMobile, setIsMobile] = useState(
    () => window.matchMedia('(max-width: 640px)').matches,
  )

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 640px)')
    const handleChange = (event: MediaQueryListEvent) => {
      setIsMobile(event.matches)
    }

    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [])

  useEffect(() => {
    if (isMobile) {
      setCollapsed(true)
    }
  }, [isMobile, setCollapsed])

  return (
    <AntLayout
      className={`admin-shell ${isMobile && !collapsed ? 'admin-shell--mobile-nav-open' : ''}`}
    >
      <AppSider />
      {isMobile && !collapsed ? (
        <button
          aria-label="关闭侧栏"
          className="admin-shell__navigation-scrim"
          onClick={() => setCollapsed(true)}
          type="button"
        />
      ) : null}
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
