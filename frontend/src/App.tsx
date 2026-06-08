import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Layout } from 'antd'
import HomePage from './pages/Home'
import KnowledgePage from './pages/Knowledge'
import KnowledgeDetailPage from './pages/Knowledge/Detail'
import PracticePage from './pages/Practice'
import ChatPage from './pages/Chat'
import AppHeader from './components/Layout/Header'
import AppFooter from './components/Layout/Footer'
import ErrorBoundary from './components/ErrorBoundary'

const { Content } = Layout
const queryClient = new QueryClient()

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <Router>
          <Layout style={{ minHeight: '100vh' }}>
            <AppHeader />
            <Content style={{ padding: '24px', background: '#f0f2f5' }}>
              <Routes>
                <Route path="/" element={<HomePage />} />
                <Route path="/knowledge" element={<KnowledgePage />} />
                <Route path="/knowledge/:id" element={<KnowledgeDetailPage />} />
                <Route path="/practice" element={<PracticePage />} />
                <Route path="/chat" element={<ChatPage />} />
              </Routes>
            </Content>
            <AppFooter />
          </Layout>
        </Router>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

export default App
