import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AdminUser } from '@/types'

interface Notification {
  id: string
  type: 'info' | 'success' | 'warning' | 'error'
  message: string
  created_at: string
}

interface AdminState {
  // 用户信息
  user: AdminUser | null
  token: string | null

  // 权限
  permissions: string[]

  // 全局状态
  collapsed: boolean
  theme: 'light' | 'dark'

  // 通知
  notifications: Notification[]

  // Actions
  setUser: (user: AdminUser | null) => void
  setToken: (token: string | null) => void
  setPermissions: (permissions: string[]) => void
  toggleCollapsed: () => void
  setTheme: (theme: 'light' | 'dark') => void
  addNotification: (notification: Notification) => void
  removeNotification: (id: string) => void
  logout: () => void
}

export const useAdminStore = create<AdminState>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      permissions: [],
      collapsed: false,
      theme: 'light',
      notifications: [],

      setUser: (user) => set({ user }),
      setToken: (token) => set({ token }),
      setPermissions: (permissions) => set({ permissions }),
      toggleCollapsed: () => set((state) => ({ collapsed: !state.collapsed })),
      setTheme: (theme) => set({ theme }),
      addNotification: (notification) =>
        set((state) => ({
          notifications: [...state.notifications, notification],
        })),
      removeNotification: (id) =>
        set((state) => ({
          notifications: state.notifications.filter((n) => n.id !== id),
        })),
      logout: () =>
        set({
          user: null,
          token: null,
          permissions: [],
        }),
    }),
    {
      name: 'admin-storage',
      partialize: (state) => ({
        user: state.user,
        token: state.token,
        permissions: state.permissions,
        collapsed: state.collapsed,
        theme: state.theme,
      }),
    }
  )
)
