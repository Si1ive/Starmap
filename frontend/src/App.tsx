import { lazy, ReactNode, Suspense, useEffect } from 'react'
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom'
import { postLoginPath } from './auth'
import AppShell from './components/AppShell'
import useAuth from './useAuth'

const AgentPage = lazy(() => import('./pages/AgentPage'))
const AccountPage = lazy(() => import('./pages/AccountPage'))
const EmailVerificationPage = lazy(
  () => import('./pages/EmailVerificationPage'),
)
const LoginPage = lazy(() => import('./pages/LoginPage'))
const MistakesPage = lazy(() => import('./pages/MistakesPage'))
const PasswordRecoveryPage = lazy(() => import('./pages/PasswordRecoveryPage'))
const PracticePage = lazy(() => import('./pages/PracticePage'))
const PracticeLibraryPage = lazy(() => import('./pages/PracticeLibraryPage'))
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

function OAuthSuccessCleanup() {
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    const search = new URLSearchParams(location.search)
    if (search.get('oauth') !== 'success') return

    search.delete('oauth')
    search.delete('new_user')
    const nextSearch = search.toString()
    navigate(
      {
        pathname: location.pathname,
        search: nextSearch ? `?${nextSearch}` : '',
        hash: location.hash,
      },
      { replace: true },
    )
  }, [location.hash, location.pathname, location.search, navigate])

  return null
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
      <OAuthSuccessCleanup />
      <Routes>
        <Route path="/login" element={<LoginRoute />} />
        <Route path="/verify-email" element={<EmailVerificationPage />} />
        <Route
          path="/forgot-password"
          element={<PasswordRecoveryPage mode="forgot" />}
        />
        <Route
          path="/reset-password"
          element={<PasswordRecoveryPage mode="reset" />}
        />
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/" element={<Navigate replace to="/agent" />} />
          <Route path="/today" element={<Navigate replace to="/progress" />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/agent" element={<AgentPage />} />
          <Route path="/agent/:threadId" element={<AgentPage />} />
          <Route path="/progress" element={<TodayPage />} />
          <Route path="/map" element={<Navigate replace to="/progress" />} />
          <Route path="/practice" element={<PracticeLibraryPage />} />
          <Route path="/practice/:sessionId" element={<PracticePage />} />
          <Route path="/practice/:sessionId/:view" element={<PracticePage />} />
          <Route path="/mistakes" element={<MistakesPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/states" element={<StateGalleryPage />} />

          <Route path="/knowledge" element={<Navigate replace to="/progress" />} />
          <Route path="/knowledge/:id" element={<Navigate replace to="/progress?point=queue" />} />
          <Route path="/chat" element={<Navigate replace to="/agent" />} />
          <Route path="*" element={<Navigate replace to="/agent" />} />
        </Route>
      </Routes>
    </Suspense>
  )
}

export default App
