import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { Layout } from 'antd'
import SearchPage from './pages/Search'
import PersonPage from './pages/Person'
import ChatPage from './pages/Chat'
import GraphPage from './pages/Graph'
import BrowsePage from './pages/Browse'
import AppHeader from './components/Layout/Header'
import AppFooter from './components/Layout/Footer'
import ErrorBoundary from './components/ErrorBoundary'

const { Content } = Layout

function App() {
  return (
    <ErrorBoundary>
      <Router>
        <Layout style={{ minHeight: '100vh' }}>
          <AppHeader />
          <Content style={{ padding: '24px', background: '#f0f2f5' }}>
            <Routes>
              <Route path="/" element={<SearchPage />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/person/:id" element={<PersonPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/graph/:id" element={<GraphPage />} />
              <Route path="/browse" element={<BrowsePage />} />
            </Routes>
          </Content>
          <AppFooter />
        </Layout>
      </Router>
    </ErrorBoundary>
  )
}

export default App
