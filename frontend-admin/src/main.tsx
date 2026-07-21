import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './index.css'
import './styles/markdown.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5 * 60 * 1000,
    },
  },
})

const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('Root element #root was not found')
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ConfigProvider
          componentSize="middle"
          locale={zhCN}
          theme={{
            token: {
              colorPrimary: '#31594e',
              colorInfo: '#31594e',
              colorLink: '#31594e',
              colorSuccess: '#4c7568',
              colorWarning: '#b87922',
              colorError: '#b24c45',
              colorText: '#18211d',
              colorTextSecondary: '#5f6d66',
              colorTextTertiary: '#7b8982',
              colorBorder: '#dce4df',
              colorBorderSecondary: '#e7ede9',
              colorBgLayout: '#f4f7f5',
              colorBgContainer: '#ffffff',
              colorFillAlter: '#f8faf9',
              borderRadius: 6,
              borderRadiusLG: 8,
              controlHeight: 36,
              fontFamily:
                'Inter, "SF Pro Text", "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif',
              fontSize: 13,
              lineWidth: 1,
              wireframe: false,
            },
            components: {
              Button: {
                fontWeight: 580,
                defaultShadow: 'none',
                primaryShadow: 'none',
                dangerShadow: 'none',
                defaultColor: '#31594e',
                defaultBg: '#ffffff',
                defaultBorderColor: '#c6d6cf',
                defaultHoverBg: '#eef4f0',
                defaultHoverColor: '#24453a',
                defaultHoverBorderColor: '#31594e',
                defaultActiveBg: '#e4ece8',
                defaultActiveColor: '#24453a',
                defaultActiveBorderColor: '#24453a',
                textTextColor: '#31594e',
                textTextHoverColor: '#24453a',
                textTextActiveColor: '#24453a',
                textHoverBg: '#eef4f0',
                linkHoverBg: 'transparent',
              },
              Layout: {
                bodyBg: '#f4f7f5',
                headerBg: '#ffffff',
                siderBg: '#edf2ef',
              },
              Menu: {
                itemBg: 'transparent',
                itemColor: '#4f5d56',
                itemHoverBg: 'rgba(255, 255, 255, 0.7)',
                itemHoverColor: '#18211d',
                itemSelectedBg: '#ffffff',
                itemSelectedColor: '#18211d',
                subMenuItemBg: 'transparent',
              },
              Table: {
                headerBg: '#f8faf9',
                headerColor: '#4f5d56',
                rowHoverBg: '#f7faf8',
                borderColor: '#e2e9e5',
              },
              Tabs: {
                inkBarColor: '#31594e',
                itemActiveColor: '#24453a',
                itemSelectedColor: '#18211d',
              },
            },
          }}
        >
          <App />
        </ConfigProvider>
      </QueryClientProvider>
    </BrowserRouter>
  </React.StrictMode>
)
