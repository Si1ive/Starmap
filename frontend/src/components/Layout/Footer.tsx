import React from 'react'
import { Layout } from 'antd'

const { Footer } = Layout

const AppFooter: React.FC = () => {
  return (
    <Footer style={{ textAlign: 'center', background: '#f0f2f5' }}>
      408考研智能学习平台 ©2026 - 基于RAG的结构化学习系统
    </Footer>
  )
}

export default AppFooter