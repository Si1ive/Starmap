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
import CrawlerStats from '@/pages/Crawler/Stats'
import CrawlerConfig from '@/pages/Crawler/Config'
import CrawlerSources from '@/pages/Crawler/Sources'
import CrawlerSchedules from '@/pages/Crawler/Schedules'
import CrawlerLogs from '@/pages/Crawler/Logs'
import ConversationList from '@/pages/Conversation/List'
import ConversationDetail from '@/pages/Conversation/Detail'
import MonitorOverview from '@/pages/Monitor/Overview'
import ApiMonitor from '@/pages/Monitor/Api'
import DatabaseMonitor from '@/pages/Monitor/Database'
import MonitorErrors from '@/pages/Monitor/Errors'
import Settings from '@/pages/Settings'
import SettingsUsers from '@/pages/Settings/Users'

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
        <Route
          path="crawler/stats"
          element={
            <PrivateRoute permission="crawler:manage">
              <CrawlerStats />
            </PrivateRoute>
          }
        />
        <Route
          path="crawler/config"
          element={
            <PrivateRoute permission="crawler:manage">
              <CrawlerConfig />
            </PrivateRoute>
          }
        />
        <Route
          path="crawler/sources"
          element={
            <PrivateRoute permission="crawler:manage">
              <CrawlerSources />
            </PrivateRoute>
          }
        />
        <Route
          path="crawler/schedules"
          element={
            <PrivateRoute permission="crawler:manage">
              <CrawlerSchedules />
            </PrivateRoute>
          }
        />
        <Route path="crawler/logs" element={<CrawlerLogs />} />

        {/* 对话管理 */}
        <Route path="conversations" element={<ConversationList />} />
        <Route path="conversations/:id" element={<ConversationDetail />} />

        {/* 系统监控 */}
        <Route path="monitor" element={<MonitorOverview />} />
        <Route
          path="monitor/api"
          element={
            <PrivateRoute permission="monitor:view">
              <ApiMonitor />
            </PrivateRoute>
          }
        />
        <Route
          path="monitor/database"
          element={
            <PrivateRoute permission="monitor:view">
              <DatabaseMonitor />
            </PrivateRoute>
          }
        />
        <Route
          path="monitor/errors"
          element={
            <PrivateRoute permission="monitor:view">
              <MonitorErrors />
            </PrivateRoute>
          }
        />

        {/* 系统配置 */}
        <Route
          path="settings"
          element={
            <PrivateRoute permission="settings:manage">
              <Settings />
            </PrivateRoute>
          }
        />
        <Route
          path="settings/users"
          element={
            <PrivateRoute permission="user:manage">
              <SettingsUsers />
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