import { Routes, Route, Navigate } from 'react-router-dom'
import { useAdminStore } from '@/store'
import Layout from '@/components/Layout'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
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
import LLMMonitor from '@/pages/Monitor/Llm'
import OutlineList from '@/pages/Outline'
import Settings from '@/pages/Settings'
import SettingsUsers from '@/pages/Settings/Users'
import KnowledgeList from '@/pages/Knowledge/List'
import KnowledgeDetail from '@/pages/Knowledge/Detail'
import KnowledgeEdit from '@/pages/Knowledge/Edit'
import QuestionList from '@/pages/Question/List'
import QuestionDetail from '@/pages/Question/Detail'
import QuestionEdit from '@/pages/Question/Edit'
import CorpusPage from '@/pages/Corpus'
import DocumentDetailPage from '@/pages/Corpus/DocumentDetail'
import SectionReviewPage from '@/pages/Review/Sections'
import KnowledgeReviewPage from '@/pages/Review/Knowledge'
import QuestionReviewPage from '@/pages/Review/Questions'
import RelationReviewPage from '@/pages/Review/Relations'
import ChapterRelationReviewPage from '@/pages/Review/ChapterRelations'
import SearchDebugPage from '@/pages/Search'
import { usePermission } from '@/hooks/usePermission'

// 路由守卫组件
const PrivateRoute = ({ children, permission }: { children: React.ReactNode; permission?: string }) => {
  const { token } = useAdminStore()
  const { hasPermission } = usePermission()

  if (!token) {
    return <Navigate to="/admin/login" replace />
  }

  if (permission && !hasPermission(permission)) {
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

        {/* 知识点管理 */}
        <Route path="knowledge" element={<KnowledgeList />} />
        <Route path="knowledge/:id" element={<KnowledgeDetail />} />
        <Route
          path="knowledge/:id/edit"
          element={
            <PrivateRoute permission="knowledge:edit">
              <KnowledgeEdit />
            </PrivateRoute>
          }
        />

        {/* 题目管理 */}
        <Route path="questions" element={<QuestionList />} />
        <Route path="questions/:id" element={<QuestionDetail />} />
        <Route
          path="questions/:id/edit"
          element={
            <PrivateRoute permission="question:edit">
              <QuestionEdit />
            </PrivateRoute>
          }
        />

        {/* 语料管理 */}
        <Route path="ingest" element={<Navigate to="/admin/corpus" replace />} />
        <Route path="corpus" element={<CorpusPage />} />
        <Route path="corpus/:id" element={<DocumentDetailPage />} />
        <Route path="outlines" element={<OutlineList />} />

        {/* 审核中心 */}
        <Route path="review/sections" element={<SectionReviewPage />} />
        <Route path="review/knowledge" element={<KnowledgeReviewPage />} />
        <Route path="review/questions" element={<QuestionReviewPage />} />
        <Route path="review/relations" element={<RelationReviewPage />} />
        <Route path="review/chapter-relations" element={<ChapterRelationReviewPage />} />

        {/* 检索调试 */}
        <Route path="search" element={<SearchDebugPage />} />

        {/* 对话管理 */}
        <Route path="conversations" element={<ConversationList />} />
        <Route path="conversations/:id" element={<ConversationDetail />} />

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
        <Route
          path="monitor/llm"
          element={
            <PrivateRoute permission="monitor:view">
              <LLMMonitor />
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
