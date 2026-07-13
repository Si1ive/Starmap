import { lazy, Suspense } from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Layout, Spin } from 'antd'
import AppHeader from './components/Layout/Header'
import AppFooter from './components/Layout/Footer'
import ErrorBoundary from './components/ErrorBoundary'

const { Content } = Layout
const queryClient = new QueryClient()
const HomePage = lazy(() => import('./pages/Home'))
const KnowledgePage = lazy(() => import('./pages/Knowledge'))
const KnowledgeDetailPage = lazy(() => import('./pages/Knowledge/Detail'))
const PracticePage = lazy(() => import('./pages/Practice'))
const ChatPage = lazy(() => import('./pages/Chat'))

const PageFallback = () => (
  <div style={{ display: 'grid', minHeight: 320, placeItems: 'center' }}>
    <Spin size="large" />
  </div>
)

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <Router>
          <Layout style={{ minHeight: '100vh' }}>
            <AppHeader />
            <Content style={{ padding: '24px', background: '#f0f2f5' }}>
              <Suspense fallback={<PageFallback />}>
                <Routes>
                  <Route path="/" element={<HomePage />} />
                  <Route path="/knowledge" element={<KnowledgePage />} />
                  <Route path="/knowledge/:id" element={<KnowledgeDetailPage />} />
                  <Route path="/practice" element={<PracticePage />} />
                  <Route path="/chat" element={<ChatPage />} />
                </Routes>
              </Suspense>
            </Content>
            <AppFooter />
          </Layout>
        </Router>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

export default App
