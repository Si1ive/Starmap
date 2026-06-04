import adminClient from './client'
import type { ApiResponse, DashboardStats } from '@/types'

export const getDashboardStats = (): Promise<ApiResponse<DashboardStats>> => {
  return adminClient.get('/dashboard/stats')
}

export const getDashboardCharts = (): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/dashboard/charts')
}
