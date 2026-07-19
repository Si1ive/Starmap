import { lazy, Suspense, type ReactNode } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Spin } from 'antd'
import { useAdminStore } from '@/store'
import Layout from '@/components/Layout'
import { usePermission } from '@/hooks/usePermission'

const Login = lazy(() => import('@/pages/Login'))
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const CrawlerList = lazy(() => import('@/pages/Crawler/List'))
const CrawlerStats = lazy(() => import('@/pages/Crawler/Stats'))
const CrawlerConfig = lazy(() => import('@/pages/Crawler/Config'))
const CrawlerSources = lazy(() => import('@/pages/Crawler/Sources'))
const CrawlerSchedules = lazy(() => import('@/pages/Crawler/Schedules'))
const CrawlerLogs = lazy(() => import('@/pages/Crawler/Logs'))
const ConversationList = lazy(() => import('@/pages/Conversation/List'))
const ConversationDetail = lazy(() => import('@/pages/Conversation/Detail'))
const MonitorOverview = lazy(() => import('@/pages/Monitor/Overview'))
const ApiMonitor = lazy(() => import('@/pages/Monitor/Api'))
const DatabaseMonitor = lazy(() => import('@/pages/Monitor/Database'))
const MonitorErrors = lazy(() => import('@/pages/Monitor/Errors'))
const LLMMonitor = lazy(() => import('@/pages/Monitor/Llm'))
const VectorRecallMonitor = lazy(() => import('@/pages/Monitor/VectorRecall'))
const OutlineList = lazy(() => import('@/pages/Outline'))
const Settings = lazy(() => import('@/pages/Settings'))
const SettingsUsers = lazy(() => import('@/pages/Settings/Users'))
const KnowledgeList = lazy(() => import('@/pages/Knowledge/List'))
const KnowledgeDetail = lazy(() => import('@/pages/Knowledge/Detail'))
const KnowledgeEdit = lazy(() => import('@/pages/Knowledge/Edit'))
const QuestionList = lazy(() => import('@/pages/Question/List'))
const QuestionDetail = lazy(() => import('@/pages/Question/Detail'))
const QuestionEdit = lazy(() => import('@/pages/Question/Edit'))
const CorpusPage = lazy(() => import('@/pages/Corpus'))
const DocumentDetailPage = lazy(() => import('@/pages/Corpus/DocumentDetail'))
const RelationReviewPage = lazy(() => import('@/pages/Review/Relations'))
const ChapterRelationReviewPage = lazy(() => import('@/pages/Review/ChapterRelations'))
const ChapterRelationGraphPage = lazy(() => import('@/pages/Review/ChapterRelationGraph'))
const SearchDebugPage = lazy(() => import('@/pages/Search'))

const PageFallback = () => (
  <div className="admin-page-loading">
    <Spin size="large" />
  </div>
)

// 路由守卫组件
const PrivateRoute = ({ children, permission }: { children: ReactNode; permission?: string }) => {
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

const PublicRoute = ({ children }: { children: ReactNode }) => {
  const { token } = useAdminStore()

  if (token) {
    return <Navigate to="/admin/dashboard" replace />
  }

  return <>{children}</>
}

const AppRoutes = () => {
  return (
    <Suspense fallback={<PageFallback />}>
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

        {/* 旧审核入口保留兼容，审核能力已合并到管理页 */}
        <Route
          path="review/knowledge"
          element={<Navigate to="/admin/knowledge?review_status=pending" replace />}
        />
        <Route
          path="review/questions"
          element={<Navigate to="/admin/questions?review_status=pending" replace />}
        />
        <Route path="review/relations" element={<RelationReviewPage />} />
        <Route path="review/chapter-relations" element={<ChapterRelationReviewPage />} />
        <Route path="review/chapter-relation-graph" element={<ChapterRelationGraphPage />} />

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
        <Route
          path="monitor/vector-recall"
          element={
            <PrivateRoute permission="monitor:view">
              <VectorRecallMonitor />
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
    </Suspense>
  )
}

export default AppRoutes
