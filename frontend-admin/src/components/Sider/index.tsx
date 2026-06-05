import { useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu } from 'antd'
import {
  DashboardOutlined,
  UserOutlined,
  VideoCameraOutlined,
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
} from '@ant-design/icons'
import { useAdminStore } from '@/store'

const { Sider } = Layout

const menuItems = [
  { key: '/admin/dashboard', icon: <DashboardOutlined />, label: '数据看板' },
  { key: '/admin/persons', icon: <UserOutlined />, label: '艺人管理' },
  { key: '/admin/works', icon: <VideoCameraOutlined />, label: '作品管理' },
  {
    key: '/admin/crawler-group',
    icon: <BugOutlined />,
    label: '爬虫管理',
    children: [
      { key: '/admin/crawler', label: '任务列表' },
      { key: '/admin/crawler/sources', label: '数据源' },
      { key: '/admin/crawler/schedules', label: '定时任务' },
      { key: '/admin/crawler/logs', label: '日志查看' },
      { key: '/admin/crawler/stats', icon: <BarChartOutlined />, label: '爬取统计' },
      { key: '/admin/crawler/config', icon: <ToolOutlined />, label: '爬虫配置' },
    ],
  },
  { key: '/admin/conversations', icon: <MessageOutlined />, label: '对话管理' },
  {
    key: '/admin/monitor-group',
    icon: <MonitorOutlined />,
    label: '系统监控',
    children: [
      { key: '/admin/monitor', label: '概览' },
      { key: '/admin/monitor/api', icon: <ApiOutlined />, label: 'API性能' },
      { key: '/admin/monitor/database', icon: <DatabaseOutlined />, label: '数据库' },
      { key: '/admin/monitor/errors', icon: <WarningOutlined />, label: '错误日志' },
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
  const { collapsed, permissions } = useAdminStore()

  // 根据权限过滤菜单项
  const filterByPermission = (items: any[]) => {
    return items.filter((item) => {
      // 配置管理子项需要 settings:manage 权限
      if (item.key.startsWith('/admin/settings')) {
        return permissions.includes('settings:manage')
      }
      // 爬虫管理子项需要 crawler:manage 权限
      if (item.key.startsWith('/admin/crawler/')) {
        return permissions.includes('crawler:manage')
      }
      // 监控管理子项需要 monitor:view 权限
      if (item.key.startsWith('/admin/monitor/')) {
        return permissions.includes('monitor:view')
      }
      // 有子菜单的项：如果子菜单全被过滤掉，则隐藏父菜单
      if (item.children) {
        item.children = filterByPermission(item.children)
        return item.children.length > 0
      }
      return true
    })
  }

  const filteredItems = filterByPermission([...menuItems])

  // 获取当前选中的菜单key和展开的子菜单key
  const selectedKey = location.pathname
  const openKeys = ['/admin/crawler-group', '/admin/monitor-group', '/admin/settings-group'].filter(
    (key) => location.pathname.startsWith(key.replace('-group', '').replace('/admin/settings-group', '/admin/settings'))
  )

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
        }}
      >
        {collapsed ? 'SM' : 'StarMap Admin'}
      </div>
      <Menu
        theme="dark"
        mode="inline"
        selectedKeys={[selectedKey]}
        defaultOpenKeys={collapsed ? [] : openKeys}
        items={filteredItems}
        onClick={({ key }) => navigate(key)}
        style={{ borderRight: 0 }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: 0,
          width: '100%',
          padding: '16px',
          color: 'rgba(255,255,255,0.45)',
          fontSize: 12,
          textAlign: 'center',
          borderTop: '1px solid rgba(255,255,255,0.1)',
        }}
      >
        {collapsed ? '©' : '© 2026 StarMap'}
      </div>
    </Sider>
  )
}

export default AppSider
