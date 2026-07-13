import { useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu } from 'antd'
import { useState, useEffect, useMemo } from 'react'
import {
  DashboardOutlined,
  BookOutlined,
  QuestionCircleOutlined,
  BugOutlined,
  BarChartOutlined,
  ToolOutlined,
  MessageOutlined,
  MonitorOutlined,
  ApiOutlined,
  DatabaseOutlined,
  WarningOutlined,
  SettingOutlined,
  TeamOutlined,
  FileTextOutlined,
  AuditOutlined,
  SearchOutlined,
  BranchesOutlined,
  ThunderboltOutlined,
  ApartmentOutlined,
  ShareAltOutlined,
  AimOutlined,
} from '@ant-design/icons'
import { useAdminStore } from '@/store'
import { usePermission } from '@/hooks/usePermission'

const { Sider } = Layout

const menuItems = [
  { key: '/admin/dashboard', icon: <DashboardOutlined />, label: '数据看板' },
  { key: '/admin/knowledge', icon: <BookOutlined />, label: '知识点管理' },
  { key: '/admin/questions', icon: <QuestionCircleOutlined />, label: '题目管理' },
  { key: '/admin/corpus', icon: <FileTextOutlined />, label: '语料管理' },
  { key: '/admin/outlines', icon: <ApartmentOutlined />, label: '大纲管理' },
  {
    key: '/admin/review-group',
    icon: <AuditOutlined />,
    label: '关系管理',
    children: [
      { key: '/admin/review/relations', icon: <BranchesOutlined />, label: '关系审核' },
      { key: '/admin/review/chapter-relations', icon: <ApartmentOutlined />, label: '考点关联审核' },
      { key: '/admin/review/chapter-relation-graph', icon: <ShareAltOutlined />, label: '考点关联图谱' },
    ],
  },
  { key: '/admin/search', icon: <SearchOutlined />, label: '检索调试' },
  { key: '/admin/conversations', icon: <MessageOutlined />, label: '智能问答' },
  {
    key: '/admin/crawler-group',
    icon: <BugOutlined />,
    label: '数据采集',
    children: [
      { key: '/admin/crawler', label: '任务列表' },
      { key: '/admin/crawler/sources', label: '数据源' },
      { key: '/admin/crawler/schedules', label: '定时任务' },
      { key: '/admin/crawler/logs', label: '日志查看' },
      { key: '/admin/crawler/stats', icon: <BarChartOutlined />, label: '爬取统计' },
      { key: '/admin/crawler/config', icon: <ToolOutlined />, label: '爬虫配置' },
    ],
  },
  {
    key: '/admin/monitor-group',
    icon: <MonitorOutlined />,
    label: '系统监控',
    children: [
      { key: '/admin/monitor', label: '概览' },
      { key: '/admin/monitor/llm', icon: <ThunderboltOutlined />, label: 'LLM 调用' },
      { key: '/admin/monitor/api', icon: <ApiOutlined />, label: 'API性能' },
      { key: '/admin/monitor/database', icon: <DatabaseOutlined />, label: '数据库' },
      { key: '/admin/monitor/errors', icon: <WarningOutlined />, label: '服务日志' },
      { key: '/admin/monitor/vector-recall', icon: <AimOutlined />, label: '向量召回' },
    ],
  },
  {
    key: '/admin/settings-group',
    icon: <SettingOutlined />,
    label: '系统配置',
    children: [
      { key: '/admin/settings', label: '基础配置' },
      { key: '/admin/settings/users', icon: <TeamOutlined />, label: '用户管理' },
    ],
  },
]

const AppSider = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const { collapsed } = useAdminStore()
  const { hasPermission } = usePermission()

  // 根据权限过滤菜单项
  const canAccessMenuItem = (key: string) => {
    if (key.startsWith('/admin/settings')) {
      return hasPermission('settings:manage')
    }
    if (key.startsWith('/admin/crawler/')) {
      return hasPermission('crawler:manage')
    }
    if (key.startsWith('/admin/monitor/')) {
      return hasPermission('monitor:view')
    }
    return true
  }

  const filterByPermission = (items: any[]): any[] =>
    items.reduce<any[]>((filteredItems, item) => {
      const nextItem = { ...item }

      if (nextItem.children) {
        nextItem.children = filterByPermission(nextItem.children)
        if (!nextItem.children.length) {
          return filteredItems
        }
      }

      if (!canAccessMenuItem(String(nextItem.key))) {
        return filteredItems
      }

      filteredItems.push(nextItem)
      return filteredItems
    }, [])

  const filteredItems = filterByPermission([...menuItems])

  // 获取当前选中的菜单key和展开的子菜单key
  const selectedKey = location.pathname
  const defaultOpenKeys = useMemo(
    () =>
      ['/admin/crawler-group', '/admin/monitor-group', '/admin/settings-group', '/admin/review-group'].filter(
        (key) => location.pathname.startsWith(key.replace('-group', '').replace('/admin/settings-group', '/admin/settings')),
      ),
    [location.pathname],
  )

  // 使用 state 管理展开的菜单（受控组件）
  const [openKeys, setOpenKeys] = useState<string[]>(collapsed ? [] : defaultOpenKeys)

  // collapsed 变化时重置 openKeys
  useEffect(() => {
    if (collapsed) {
      setOpenKeys([])
    } else {
      setOpenKeys(defaultOpenKeys)
    }
  }, [collapsed, defaultOpenKeys])

  return (
    <Sider
      trigger={null}
      collapsible
      collapsed={collapsed}
      style={{
        overflow: 'auto',
        height: '100vh',
        position: 'fixed',
        left: 0,
        top: 0,
        bottom: 0,
        zIndex: 100,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontSize: collapsed ? 16 : 20,
          fontWeight: 'bold',
          borderBottom: '1px solid rgba(255,255,255,0.1)',
          flex: '0 0 64px',
        }}
      >
        {collapsed ? '408' : '408考研学习平台'}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden', paddingBottom: 8 }}>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          openKeys={openKeys}
          onOpenChange={setOpenKeys}
          items={filteredItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderRight: 0 }}
        />
      </div>
      <div
        style={{
          width: '100%',
          padding: '16px',
          color: 'rgba(255,255,255,0.45)',
          fontSize: 12,
          textAlign: 'center',
          borderTop: '1px solid rgba(255,255,255,0.1)',
          flex: '0 0 auto',
        }}
      >
        {collapsed ? '©' : '© 2026 StarMap'}
      </div>
    </Sider>
  )
}

export default AppSider
