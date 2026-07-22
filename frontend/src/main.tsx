import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import 'katex/dist/katex.min.css'
import App from './App'
import AuthProvider from './AuthProvider'
import { AgentProvider } from './store/agent-context'
import './index.css'

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Root element #root was not found')
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <AuthProvider>
      <AgentProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
      </AgentProvider>
    </AuthProvider>
  </React.StrictMode>
)
