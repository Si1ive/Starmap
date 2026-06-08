import React from 'react'
import { Layout, Menu } from 'antd'
import { Link, useLocation } from 'react-router-dom'
import { HomeOutlined, BookOutlined, MessageOutlined, FormOutlined } from '@ant-design/icons'

const { Header } = Layout

const AppHeader: React.FC = () => {
  const location = useLocation()

  const menuItems = [
    { key: '/', icon: <HomeOutlined />, label: <Link to="/">首页</Link> },
    { key: '/knowledge', icon: <BookOutlined />, label: <Link to="/knowledge">知识库</Link> },
    { key: '/practice', icon: <FormOutlined />, label: <Link to="/practice">刷题</Link> },
    { key: '/chat', icon: <MessageOutlined />, label: <Link to="/chat">智能问答</Link> },
  ]

  return (
    <Header style={{ background: '#fff', boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }}>
      <div style={{ display: 'flex', alignItems: 'center', maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ fontSize: 20, fontWeight: 'bold', marginRight: 40, color: '#1890ff' }}>
          408考研学习平台
        </div>
        <Menu
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={menuItems}
          style={{ flex: 1, borderBottom: 'none' }}
        />
      </div>
    </Header>
  )
}

export default AppHeader
