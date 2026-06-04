import adminClient from './client'
import type { ApiResponse } from '@/types'

export const getApiMonitor = (): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/monitor/api')
}

export const getDatabaseMonitor = (): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/monitor/database')
}

export const getErrorLogs = (params?: {
  level?: string
  service?: string
  start_time?: string
  end_time?: string
  page?: number
  page_size?: number
}): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/monitor/errors', { params })
}
