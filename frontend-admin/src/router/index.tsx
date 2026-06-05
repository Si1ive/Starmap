import { Routes, Route, Navigate } from 'react-router-dom'
import { useAdminStore } from '@/store'
import Layout from '@/components/Layout'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import PersonList from '@/pages/Person/List'
import PersonDetail from '@/pages/Person/Detail'
import PersonEdit from '@/pages/Person/Edit'
import WorkList from '@/pages/Work/List'
import WorkDetail from '@/pages/Work/Detail'
import WorkEdit from '@/pages/Work/Edit'
import CrawlerList from '@/pages/Crawler/List'
import ConversationList from '@/pages/Conversation/List'
import ConversationDetail from '@/pages/Conversation/Detail'
import MonitorOverview from '@/pages/Monitor/Overview'
import Settings from '@/pages/Settings'

// 路由守卫组件
const PrivateRoute = ({ children, permission }: { children: React.ReactNode; permission?: string }) => {
  const { token, permissions } = useAdminStore()

  if (!token) {
    return <Navigate to="/admin/login" replace />
  }

  if (permission && !permissions.includes(permission)) {
    return <Navigate to="/admin/dashboard" replace />
  }

  return <>{children}</>
}

const PublicRoute = ({ children }: { children: React.ReactNode }) => {
  const { token } = useAdminStore()

  if (token) {
    return <Navigate to="/admin/dashboard" replace />
  }

  return <>{children}</>
}

const AppRoutes = () => {
  return (
    <Routes>
      {/* 公开路由 */}
      <Route
        path="/admin/login"
        element={
          <PublicRoute>
            <Login />
          </PublicRoute>
        }
      />

      {/* 需要认证的路由 */}
      <Route
        path="/admin"
        element={
          <PrivateRoute>
            <Layout />
          </PrivateRoute>
        }
      >
        <Route index element={<Navigate to="/admin/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        
        {/* 艺人管理 */}
        <Route path="persons" element={<PersonList />} />
        <Route path="persons/:id" element={<PersonDetail />} />
        <Route
          path="persons/:id/edit"
          element={
            <PrivateRoute permission="person:edit">
              <PersonEdit />
            </PrivateRoute>
          }
        />
        <Route
          path="persons/new"
          element={
            <PrivateRoute permission="person:edit">
              <PersonEdit />
            </PrivateRoute>
          }
        />

        {/* 作品管理 */}
        <Route path="works" element={<WorkList />} />
        <Route path="works/:id" element={<WorkDetail />} />
        <Route
          path="works/:id/edit"
          element={
            <PrivateRoute permission="work:edit">
              <WorkEdit />
            </PrivateRoute>
          }
        />
        <Route
          path="works/new"
          element={
            <PrivateRoute permission="work:edit">
              <WorkEdit />
            </PrivateRoute>
          }
        />

        {/* 爬虫管理 */}
        <Route path="crawler" element={<CrawlerList />} />

        {/* 对话管理 */}
        <Route path="conversations" element={<ConversationList />} />
        <Route path="conversations/:id" element={<ConversationDetail />} />

        {/* 系统监控 */}
        <Route path="monitor" element={<MonitorOverview />} />

        {/* 系统配置 */}
        <Route
          path="settings"
          element={
            <PrivateRoute permission="settings:manage">
              <Settings />
            </PrivateRoute>
          }
        />
      </Route>

      {/* 默认重定向 */}
      <Route path="*" element={<Navigate to="/admin/login" replace />} />
    </Routes>
  )
}

export default AppRoutes
