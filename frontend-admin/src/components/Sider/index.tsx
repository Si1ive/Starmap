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
  RobotOutlined,
} from '@ant-design/icons'
import { useAdminStore } from '@/store'
import { usePermission } from '@/hooks/usePermission'
import AdminBrand from '../Brand'

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
      { key: '/admin/agent-runs', icon: <ThunderboltOutlined />, label: 'Agent Runs 监控' },
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
      { key: '/admin/agent-models', icon: <RobotOutlined />, label: 'Agent 模型配置' },
      { key: '/admin/settings/users', icon: <TeamOutlined />, label: '用户管理' },
    ],
  },
]

const selectableMenuKeys = [
  '/admin/review/chapter-relation-graph',
  '/admin/review/chapter-relations',
  '/admin/review/relations',
  '/admin/agent-runs',
  '/admin/agent-models',
  '/admin/crawler/schedules',
  '/admin/crawler/sources',
  '/admin/crawler/config',
  '/admin/crawler/stats',
  '/admin/crawler/logs',
  '/admin/monitor/vector-recall',
  '/admin/monitor/database',
  '/admin/monitor/errors',
  '/admin/monitor/api',
  '/admin/monitor/llm',
  '/admin/settings/users',
  '/admin/conversations',
  '/admin/knowledge',
  '/admin/questions',
  '/admin/dashboard',
  '/admin/outlines',
  '/admin/crawler',
  '/admin/monitor',
  '/admin/settings',
  '/admin/corpus',
  '/admin/search',
]

const menuGroups = [
  { key: '/admin/review-group', prefix: '/admin/review' },
  { key: '/admin/crawler-group', prefix: '/admin/crawler' },
  { key: '/admin/monitor-group', prefix: '/admin/monitor' },
  { key: '/admin/monitor-group', prefix: '/admin/agent-runs' },
  { key: '/admin/settings-group', prefix: '/admin/settings' },
  { key: '/admin/settings-group', prefix: '/admin/agent-models' },
]

const AppSider = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const { collapsed, setCollapsed } = useAdminStore()
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

  const selectedKey = useMemo(
    () =>
      selectableMenuKeys.find(
        (key) => location.pathname === key || location.pathname.startsWith(`${key}/`),
      ) ?? location.pathname,
    [location.pathname],
  )

  const defaultOpenKeys = useMemo(
    () =>
      menuGroups
        .filter(({ prefix }) => location.pathname.startsWith(prefix))
        .map(({ key }) => key),
    [location.pathname],
  )

  const [openKeys, setOpenKeys] = useState<string[]>(collapsed ? [] : defaultOpenKeys)

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
      collapsedWidth={76}
      width={236}
      className="admin-sider"
    >
      <button
        className="admin-sider__brand"
        onClick={() => navigate('/admin/dashboard')}
        type="button"
      >
        <AdminBrand compact={collapsed} />
      </button>
      <div className="admin-sider__menu">
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          openKeys={openKeys}
          onOpenChange={setOpenKeys}
          items={filteredItems}
          onClick={({ key }) => {
            navigate(key)
            if (window.matchMedia('(max-width: 640px)').matches) {
              setCollapsed(true)
            }
          }}
          className="admin-navigation"
        />
      </div>
      <div className="admin-sider__status">
        <span className="admin-sider__status-dot" />
        {collapsed ? null : <span>管理节点在线</span>}
      </div>
    </Sider>
  )
}

export default AppSider
