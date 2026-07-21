import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  BookOpenCheck,
  BotMessageSquare,
  BrainCircuit,
  ChevronDown,
  FileUp,
  History,
  Library,
  ListTodo,
  LoaderCircle,
  LogOut,
  Map,
  Menu,
  PanelLeftClose,
  UserRound,
  X,
} from 'lucide-react'
import { IconButton, StatusMark } from './Primitives'
import PlatformBrand from './PlatformBrand'
import useAuth from '../useAuth'
import { activeTasks, agentHistory } from '../data/fixtures'

const navItems = [
  { to: '/agent', label: 'Agent', icon: BotMessageSquare },
  { to: '/practice', label: '练习', icon: BookOpenCheck },
  { to: '/mistakes', label: '知识薄弱点', icon: BrainCircuit },
  { to: '/progress', label: '学习进度', icon: Map },
  { to: '/sources', label: '资料', icon: Library },
]

const mobileNav = navItems
const activeTaskIcons = {
  agent: BotMessageSquare,
  source: FileUp,
  practice: BookOpenCheck,
}

export default function AppShell() {
  const { logout, user } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [taskCenterOpen, setTaskCenterOpen] = useState(false)
  const [sidebarCompact, setSidebarCompact] = useState(false)
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState('')
  const accountMenuRef = useRef<HTMLDivElement | null>(null)
  const isPractice = location.pathname.startsWith('/practice/')
  const displayName = user?.display_name || user?.email || '学习用户'
  const avatarLabel = Array.from(displayName.trim())[0] || '学'

  const currentLabel = useMemo(() => {
    if (location.pathname.startsWith('/account')) return '账户'
    const item = navItems.find((nav) => location.pathname.startsWith(nav.to.split('?')[0]))
    return item?.label ?? '408 Agent'
  }, [location.pathname])

  useEffect(() => {
    setAccountMenuOpen(false)
    setTaskCenterOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!accountMenuOpen) return undefined

    const handlePointerDown = (event: PointerEvent) => {
      if (!accountMenuRef.current?.contains(event.target as Node)) {
        setAccountMenuOpen(false)
      }
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAccountMenuOpen(false)
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [accountMenuOpen])

  const handleLogout = async () => {
    setAccountMenuOpen(false)
    setLoggingOut(true)
    setLogoutError('')
    try {
      await logout()
      navigate('/login', { replace: true })
    } catch {
      setLogoutError('退出失败，请重试')
    } finally {
      setLoggingOut(false)
    }
  }

  return (
    <div className={`app-frame ${sidebarCompact ? 'app-frame--compact' : ''} ${isPractice ? 'app-frame--practice' : ''}`}>
      <aside className={`sidebar ${sidebarOpen ? 'sidebar--open' : ''}`}>
        <div className="sidebar__brand">
          <button className="brand-mark" onClick={() => navigate('/agent')} type="button">
            <PlatformBrand />
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
            <span>历史记录</span>
            <History size={15} />
          </div>
          {agentHistory.map((thread) => (
            <button
              key={thread.id}
              onClick={() => navigate(`/agent/${thread.id}?state=${thread.state}`)}
              type="button"
            >
              <span>{thread.title}</span>
              <small>{thread.time} · {thread.subject}</small>
            </button>
          ))}
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
            </div>
            <div className="topbar__actions">
              <div className="task-center-anchor">
                <IconButton
                  className="task-center-button"
                  label="查看进行中的任务"
                  onClick={() => setTaskCenterOpen((value) => !value)}
                >
                  <ListTodo size={19} />
                  <span className="task-dot" />
                </IconButton>
                {taskCenterOpen ? (
                  <div className="task-center">
                    <div className="task-center__header">
                      <div>
                        <p className="eyebrow">当前任务</p>
                        <h2>正在执行中的任务</h2>
                      </div>
                      <IconButton label="关闭任务中心" onClick={() => setTaskCenterOpen(false)}>
                        <X size={18} />
                      </IconButton>
                    </div>
                    {activeTasks.map((task) => {
                      const Icon = activeTaskIcons[task.kind]
                      return (
                        <button
                          className="task-center__item"
                          key={task.id}
                          onClick={() => {
                            navigate(task.route)
                            setTaskCenterOpen(false)
                          }}
                          type="button"
                        >
                          <span className={`task-center__icon task-center__icon--${task.kind}`}>
                            <Icon size={17} />
                          </span>
                          <span>
                            <strong>{task.title}</strong>
                            <small>{task.detail}</small>
                          </span>
                          <StatusMark tone={task.kind === 'source' ? 'warning' : 'running'}>
                            {task.status}
                          </StatusMark>
                        </button>
                      )
                    })}
                    <p className="task-center__note">历史记录从左侧进入。</p>
                  </div>
                ) : null}
              </div>
              <div className="account-menu-anchor" ref={accountMenuRef}>
                <button
                  aria-expanded={accountMenuOpen}
                  aria-haspopup="menu"
                  aria-label="打开账户菜单"
                  className="account-menu-button"
                  onClick={() => setAccountMenuOpen((value) => !value)}
                  type="button"
                >
                  <span className="account-menu-button__avatar">{avatarLabel}</span>
                  <ChevronDown className={accountMenuOpen ? 'is-open' : ''} size={15} />
                </button>
                {accountMenuOpen ? (
                  <div className="account-menu" role="menu">
                    <button
                      onClick={() => navigate('/account')}
                      role="menuitem"
                      type="button"
                    >
                      <UserRound size={17} />
                      <span>
                        <strong>账户与登录</strong>
                        <small>{displayName}</small>
                      </span>
                    </button>
                    <button
                      disabled={loggingOut}
                      onClick={() => void handleLogout()}
                      role="menuitem"
                      type="button"
                    >
                      {loggingOut ? <LoaderCircle className="spin" size={17} /> : <LogOut size={17} />}
                      <span>
                        <strong>{loggingOut ? '正在退出' : '退出登录'}</strong>
                        <small>结束当前设备会话</small>
                      </span>
                    </button>
                    {logoutError ? <p role="alert">{logoutError}</p> : null}
                  </div>
                ) : null}
              </div>
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
          </nav>
        ) : null}
      </div>
    </div>
  )
}
