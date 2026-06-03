import React from 'react'
import { Layout } from 'antd'

const { Footer } = Layout

const AppFooter: React.FC = () => {
  return (
    <Footer style={{ textAlign: 'center', background: '#f0f2f5' }}>
      StarMap ©2024 - 艺人知识图谱与对话Agent
    </Footer>
  )
}

export default AppFooter