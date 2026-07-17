import { lazy, ReactNode, Suspense } from 'react'
import {
  Navigate,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom'
import { postLoginPath } from './auth'
import AppShell from './components/AppShell'
import useAuth from './useAuth'

const AgentPage = lazy(() => import('./pages/AgentPage'))
const LoginPage = lazy(() => import('./pages/LoginPage'))
const MapPage = lazy(() => import('./pages/MapPage'))
const MistakesPage = lazy(() => import('./pages/MistakesPage'))
const OnboardingPage = lazy(() => import('./pages/OnboardingPage'))
const PasswordRecoveryPage = lazy(() => import('./pages/PasswordRecoveryPage'))
const PracticePage = lazy(() => import('./pages/PracticePage'))
const SourcesPage = lazy(() => import('./pages/SourcesPage'))
const StateGalleryPage = lazy(() => import('./pages/StateGalleryPage'))
const TodayPage = lazy(() => import('./pages/TodayPage'))

function RequireAuth({ children }: { children: ReactNode }) {
  const { restore, status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return <AuthenticationLoading />
  }
  if (status === 'unavailable') {
    return (
      <div className="app-loading" role="alert">
        <strong>暂时无法确认登录状态</strong>
        <p>认证服务没有响应，请稍后重试。</p>
        <button className="button button--secondary" onClick={() => void restore()} type="button">
          重新连接
        </button>
      </div>
    )
  }
  if (status === 'anonymous') {
    return <Navigate replace state={{ from: location }} to="/login" />
  }
  return children
}

function LoginRoute() {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return <AuthenticationLoading />
  }
  if (status === 'authenticated') {
    return <Navigate replace to={postLoginPath(location.state)} />
  }
  return <LoginPage />
}

function AuthenticationLoading() {
  return (
    <div className="app-loading" role="status">
      <span />
      <strong>正在确认登录状态</strong>
    </div>
  )
}

function App() {
  return (
    <Suspense
      fallback={
        <div className="app-loading" role="status">
          <span />
          <strong>正在打开学习工作台</strong>
        </div>
      }
    >
      <Routes>
        <Route path="/login" element={<LoginRoute />} />
        <Route
          path="/forgot-password"
          element={<PasswordRecoveryPage mode="forgot" />}
        />
        <Route
          path="/reset-password"
          element={<PasswordRecoveryPage mode="reset" />}
        />
        <Route
          path="/onboarding"
          element={
            <RequireAuth>
              <OnboardingPage />
            </RequireAuth>
          }
        />
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/" element={<Navigate replace to="/today" />} />
          <Route path="/today" element={<TodayPage />} />
          <Route path="/agent" element={<AgentPage />} />
          <Route path="/agent/:threadId" element={<AgentPage />} />
          <Route path="/map" element={<MapPage />} />
          <Route path="/practice" element={<Navigate replace to="/practice/queue-check?question=1" />} />
          <Route path="/practice/:sessionId" element={<PracticePage />} />
          <Route path="/practice/:sessionId/:view" element={<PracticePage />} />
          <Route path="/mistakes" element={<MistakesPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/states" element={<StateGalleryPage />} />

          <Route path="/knowledge" element={<Navigate replace to="/map" />} />
          <Route path="/knowledge/:id" element={<Navigate replace to="/map?point=queue" />} />
          <Route path="/chat" element={<Navigate replace to="/agent" />} />
          <Route path="*" element={<Navigate replace to="/today" />} />
        </Route>
      </Routes>
    </Suspense>
  )
}

export default App
