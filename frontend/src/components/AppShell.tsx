import { useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Bell,
  BookOpenCheck,
  BotMessageSquare,
  CalendarCheck2,
  ChevronDown,
  CircleUserRound,
  Clock3,
  Command,
  Ellipsis,
  Library,
  ListChecks,
  Map,
  Menu,
  MessageSquarePlus,
  PanelLeftClose,
  Search,
  Settings,
  TriangleAlert,
  X,
} from 'lucide-react'
import { IconButton, StatusMark } from './Primitives'

const navItems = [
  { to: '/today', label: '今日', icon: CalendarCheck2 },
  { to: '/agent', label: 'Agent', icon: BotMessageSquare },
  { to: '/map', label: '学习地图', icon: Map },
  { to: '/practice/queue-check?question=1', label: '练习', icon: BookOpenCheck },
  { to: '/mistakes', label: '错题', icon: ListChecks },
  { to: '/sources', label: '资料', icon: Library },
]

const mobileNav = navItems.slice(0, 5).filter((item) => item.label !== '学习地图')

export default function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [taskCenterOpen, setTaskCenterOpen] = useState(false)
  const [sidebarCompact, setSidebarCompact] = useState(false)
  const isPractice = location.pathname.startsWith('/practice/')

  const currentLabel = useMemo(() => {
    const item = navItems.find((nav) => location.pathname.startsWith(nav.to.split('?')[0]))
    return item?.label ?? '408 Agent'
  }, [location.pathname])

  return (
    <div className={`app-frame ${sidebarCompact ? 'app-frame--compact' : ''} ${isPractice ? 'app-frame--practice' : ''}`}>
      <aside className={`sidebar ${sidebarOpen ? 'sidebar--open' : ''}`}>
        <div className="sidebar__brand">
          <button className="brand-mark" onClick={() => navigate('/today')} type="button">
            <span>408</span>
            <strong>学习工作台</strong>
          </button>
          <IconButton
            className="sidebar__collapse"
            label={sidebarCompact ? '展开导航' : '收起导航'}
            onClick={() => setSidebarCompact((value) => !value)}
          >
            <PanelLeftClose size={18} />
          </IconButton>
          <IconButton className="sidebar__mobile-close" label="关闭导航" onClick={() => setSidebarOpen(false)}>
            <X size={19} />
          </IconButton>
        </div>

        <button className="new-thread" onClick={() => navigate('/agent')} type="button">
          <MessageSquarePlus size={17} />
          <span>新建学习线程</span>
          <kbd>⌘ K</kbd>
        </button>

        <nav className="primary-nav" aria-label="主要导航">
          {navItems.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                className={({ isActive }) => (isActive ? 'nav-item nav-item--active' : 'nav-item')}
                key={item.label}
                onClick={() => setSidebarOpen(false)}
                to={item.to}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </NavLink>
            )
          })}
        </nav>

        <div className="recent-threads">
          <div className="sidebar-label">
            <span>最近线程</span>
            <IconButton label="线程选项">
              <Ellipsis size={16} />
            </IconButton>
          </div>
          <button onClick={() => navigate('/agent/queue?state=complete')} type="button">
            <span>循环队列的 front 怎么算</span>
            <small>刚刚</small>
          </button>
          <button onClick={() => navigate('/agent/recovery?state=failed')} type="button">
            <span>生成 20 题专项练习</span>
            <small className="text-error">需要处理</small>
          </button>
          <button onClick={() => navigate('/agent/plan?state=approval')} type="button">
            <span>调整本周复习计划</span>
            <small className="text-amber">待确认</small>
          </button>
        </div>

        <div className="sidebar__account">
          <div className="avatar">张</div>
          <div>
            <strong>张同学</strong>
            <small><span className="sync-dot" /> 已同步</small>
          </div>
          <ChevronDown size={16} />
        </div>
      </aside>

      {sidebarOpen ? <button aria-label="关闭导航遮罩" className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} type="button" /> : null}

      <div className="app-column">
        {!isPractice ? (
          <header className="topbar">
            <div className="topbar__left">
              <IconButton className="mobile-menu" label="打开导航" onClick={() => setSidebarOpen(true)}>
                <Menu size={20} />
              </IconButton>
              <span className="topbar__page">{currentLabel}</span>
              <span className="topbar__context">强化阶段 · 距本周目标还差 3 项</span>
            </div>
            <div className="topbar__actions">
              <button className="command-shortcut" onClick={() => navigate('/agent')} type="button">
                <Search size={16} />
                <span>提问或开始任务</span>
                <kbd><Command size={12} /> K</kbd>
              </button>
              <div className="task-center-anchor">
                <IconButton
                  className="task-center-button"
                  label="任务状态中心"
                  onClick={() => setTaskCenterOpen((value) => !value)}
                >
                  <Clock3 size={19} />
                  <span className="task-dot" />
                </IconButton>
                {taskCenterOpen ? (
                  <div className="task-center">
                    <div className="task-center__header">
                      <div>
                        <p className="eyebrow">任务状态</p>
                        <h2>Agent 仍在工作</h2>
                      </div>
                      <IconButton label="关闭任务中心" onClick={() => setTaskCenterOpen(false)}>
                        <X size={18} />
                      </IconButton>
                    </div>
                    <button
                      className="task-center__item"
                      onClick={() => {
                        navigate('/agent/queue?state=running&hold=1')
                        setTaskCenterOpen(false)
                      }}
                      type="button"
                    >
                      <span className="task-center__icon task-center__icon--running">
                        <BotMessageSquare size={17} />
                      </span>
                      <span>
                        <strong>循环队列讲解</strong>
                        <small>正在组织分层讲解 · 4/6</small>
                      </span>
                      <StatusMark tone="running">运行中</StatusMark>
                    </button>
                    <button
                      className="task-center__item"
                      onClick={() => {
                        navigate('/agent/plan?state=approval')
                        setTaskCenterOpen(false)
                      }}
                      type="button"
                    >
                      <span className="task-center__icon task-center__icon--approval">
                        <Bell size={17} />
                      </span>
                      <span>
                        <strong>调整本周计划</strong>
                        <small>需要确认 1 项持续修改</small>
                      </span>
                      <StatusMark tone="warning">待确认</StatusMark>
                    </button>
                    <button
                      className="task-center__item"
                      onClick={() => {
                        navigate('/agent/recovery?state=failed')
                        setTaskCenterOpen(false)
                      }}
                      type="button"
                    >
                      <span className="task-center__icon task-center__icon--failed">
                        <TriangleAlert size={17} />
                      </span>
                      <span>
                        <strong>专项练习提示</strong>
                        <small>草稿已保留，可局部重试</small>
                      </span>
                      <StatusMark tone="error">失败</StatusMark>
                    </button>
                  </div>
                ) : null}
              </div>
              <IconButton label="设置" onClick={() => navigate('/states')}>
                <Settings size={19} />
              </IconButton>
              <CircleUserRound className="topbar__avatar" size={25} />
            </div>
          </header>
        ) : null}

        <main className="app-main">
          <Outlet />
        </main>

        {!isPractice ? (
          <nav className="mobile-bottom-nav" aria-label="移动端导航">
            {mobileNav.map((item) => {
              const Icon = item.icon
              return (
                <NavLink key={item.label} to={item.to}>
                  <Icon size={20} />
                  <span>{item.label}</span>
                </NavLink>
              )
            })}
            <button onClick={() => setSidebarOpen(true)} type="button">
              <Menu size={20} />
              <span>更多</span>
            </button>
          </nav>
        ) : null}
      </div>
    </div>
  )
}
