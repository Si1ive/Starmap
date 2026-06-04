import { useAdminStore } from '@/store'

/**
 * 权限检查 Hook
 */
export const usePermission = () => {
  const { permissions, user } = useAdminStore()

  const hasPermission = (permission: string): boolean => {
    if (!user) return false
    if (user.role === 'super') return true
    return permissions.includes(permission)
  }

  const hasRole = (role: string | string[]): boolean => {
    if (!user) return false
    if (Array.isArray(role)) {
      return role.includes(user.role)
    }
    return user.role === role
  }

  return {
    hasPermission,
    hasRole,
    isSuperAdmin: user?.role === 'super',
    isAdmin: user?.role === 'admin' || user?.role === 'super',
    isOperator: user?.role === 'operator',
  }
}
