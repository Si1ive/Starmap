import { useAdminStore } from '@/store'

/**
 * 权限检查 Hook
 */
export const usePermission = () => {
  const { permissions, user } = useAdminStore()

  const isSuperAdmin = user?.role === 'super' || user?.role === 'super_admin'

  const hasPermission = (permission: string): boolean => {
    if (!user) return false
    if (isSuperAdmin) return true
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
    isSuperAdmin,
    isAdmin: user?.role === 'admin' || user?.role === 'data_admin' || isSuperAdmin,
    isOperator: user?.role === 'operator',
  }
}
