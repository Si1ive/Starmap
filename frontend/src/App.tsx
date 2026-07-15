import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'

const AgentPage = lazy(() => import('./pages/AgentPage'))
const MapPage = lazy(() => import('./pages/MapPage'))
const MistakesPage = lazy(() => import('./pages/MistakesPage'))
const OnboardingPage = lazy(() => import('./pages/OnboardingPage'))
const PracticePage = lazy(() => import('./pages/PracticePage'))
const SourcesPage = lazy(() => import('./pages/SourcesPage'))
const StateGalleryPage = lazy(() => import('./pages/StateGalleryPage'))
const TodayPage = lazy(() => import('./pages/TodayPage'))

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
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route element={<AppShell />}>
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
