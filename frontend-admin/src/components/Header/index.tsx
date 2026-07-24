import { useLocation, useNavigate } from 'react-router-dom'
import { Layout, Button, Dropdown, Badge, Tooltip } from 'antd'
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  UserOutlined,
  LogoutOutlined,
  BellOutlined,
} from '@ant-design/icons'
import { useAdminStore } from '@/store'

const { Header } = Layout

const routeContexts = [
  { prefix: '/admin/review/chapter-relation-graph', section: '关系管理', title: '考点关联图谱' },
  { prefix: '/admin/review/chapter-relations', section: '关系管理', title: '考点关联审核' },
  { prefix: '/admin/review/relations', section: '关系管理', title: '关系审核' },
  { prefix: '/admin/crawler/schedules', section: '数据采集', title: '定时任务' },
  { prefix: '/admin/crawler/sources', section: '数据采集', title: '数据源' },
  { prefix: '/admin/crawler/config', section: '数据采集', title: '爬虫配置' },
  { prefix: '/admin/crawler/stats', section: '数据采集', title: '爬取统计' },
  { prefix: '/admin/crawler/logs', section: '数据采集', title: '运行日志' },
  { prefix: '/admin/monitor/vector-recall', section: '系统监控', title: '向量召回' },
  { prefix: '/admin/monitor/database', section: '系统监控', title: '数据库' },
  { prefix: '/admin/monitor/errors', section: '系统监控', title: '服务日志' },
  { prefix: '/admin/monitor/api', section: '系统监控', title: 'API 性能' },
  { prefix: '/admin/monitor/llm', section: '系统监控', title: 'LLM 调用' },
  { prefix: '/admin/agent-runs', section: '系统监控', title: 'Agent Runs 监控' },
  { prefix: '/admin/settings/users', section: '系统配置', title: '用户管理' },
  { prefix: '/admin/agent-models', section: '系统配置', title: 'Agent 模型配置' },
  { prefix: '/admin/conversations', section: '智能问答', title: '对话记录' },
  { prefix: '/admin/knowledge', section: '内容资产', title: '知识点管理' },
  { prefix: '/admin/questions', section: '内容资产', title: '题目管理' },
  { prefix: '/admin/dashboard', section: '运行概览', title: '数据看板' },
  { prefix: '/admin/outlines', section: '内容资产', title: '大纲管理' },
  { prefix: '/admin/crawler', section: '数据采集', title: '采集任务' },
  { prefix: '/admin/monitor', section: '系统监控', title: '运行概览' },
  { prefix: '/admin/settings', section: '系统配置', title: '基础配置' },
  { prefix: '/admin/corpus', section: '内容资产', title: '语料管理' },
  { prefix: '/admin/search', section: '检索调试', title: '召回验证' },
]

const AppHeader = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, collapsed, notifications, toggleCollapsed, logout } = useAdminStore()
  const routeContext =
    routeContexts.find(({ prefix }) => location.pathname.startsWith(prefix)) ?? routeContexts[0]

  const handleLogout = () => {
    logout()
    navigate('/admin/login')
  }

  const userMenuItems = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: '个人中心',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      danger: true,
      onClick: handleLogout,
    },
  ]

  return (
    <Header className="admin-header">
      <div className="admin-header__leading">
        <Button
          type="text"
          icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          onClick={toggleCollapsed}
          className="admin-header__toggle"
          aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
        />
        <div className="admin-header__context">
          <span>{routeContext.section}</span>
          <strong>{routeContext.title}</strong>
        </div>
      </div>

      <div className="admin-header__actions">
        <Tooltip title={notifications.length ? `${notifications.length} 条未读通知` : '暂无未读通知'}>
          <Badge count={notifications.length} size="small">
            <Button
              type="text"
              icon={<BellOutlined />}
              className="admin-header__icon-button"
              aria-label="通知"
            />
          </Badge>
        </Tooltip>

        <Dropdown menu={{ items: userMenuItems }} placement="bottomRight" trigger={['click']}>
          <button className="admin-account" type="button">
            <span className="admin-account__avatar">
              {user?.nickname?.[0] || <UserOutlined />}
            </span>
            <span className="admin-account__name">{user?.nickname || '管理员'}</span>
          </button>
        </Dropdown>
      </div>
    </Header>
  )
}

export default AppHeader
