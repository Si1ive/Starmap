import React from 'react'
import { Layout, Menu } from 'antd'
import { Link, useLocation } from 'react-router-dom'
import { HomeOutlined, SearchOutlined, MessageOutlined, GlobalOutlined } from '@ant-design/icons'

const { Header } = Layout

const AppHeader: React.FC = () => {
  const location = useLocation()

  const menuItems = [
    { key: '/', icon: <HomeOutlined />, label: <Link to="/">首页</Link> },
    { key: '/search', icon: <SearchOutlined />, label: <Link to="/search">搜索</Link> },
    { key: '/chat', icon: <MessageOutlined />, label: <Link to="/chat">对话</Link> },
    { key: '/browse', icon: <GlobalOutlined />, label: <Link to="/browse">浏览</Link> },
  ]

  return (
    <Header style={{ background: '#fff', boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }}>
      <div style={{ display: 'flex', alignItems: 'center', maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ fontSize: 20, fontWeight: 'bold', marginRight: 40 }}>
          StarMap
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