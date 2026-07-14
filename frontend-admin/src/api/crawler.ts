import adminClient from './client'
import type { ApiResponse, PaginatedResponse, CrawlerTask, CrawlerSource, CrawlerSchedule, CrawlerLog, DownloadedFile } from '@/types'

// ===== 爬虫任务 =====

export interface CrawlerTaskParams {
  page?: number
  page_size?: number
  status?: string
  task_type?: string
  source_id?: string
}

export const getCrawlerTasks = (
  params?: CrawlerTaskParams
): Promise<ApiResponse<PaginatedResponse<CrawlerTask>>> => {
  return adminClient.get('/crawler/tasks', { params })
}

export const createCrawlerTask = (data: {
  name: string
  task_type: string
  source_ids?: string[]
  config?: Record<string, unknown>
  execute_now?: boolean
}): Promise<ApiResponse<CrawlerTask>> => {
  return adminClient.post('/crawler/tasks', data)
}

export const startCrawlerTask = (id: string): Promise<ApiResponse<CrawlerTask>> => {
  return adminClient.post(`/crawler/tasks/${id}/start`)
}

export const stopCrawlerTask = (id: string): Promise<ApiResponse<CrawlerTask>> => {
  return adminClient.post(`/crawler/tasks/${id}/stop`)
}

export const deleteCrawlerTask = (id: string): Promise<ApiResponse<{ id: string }>> => {
  return adminClient.delete(`/crawler/tasks/${id}`)
}

// ===== 数据源管理 =====

export interface CrawlerSourceParams {
  page?: number
  page_size?: number
  status?: string
  source_type?: string
}

export const getCrawlerSources = (
  params?: CrawlerSourceParams
): Promise<ApiResponse<PaginatedResponse<CrawlerSource>>> => {
  return adminClient.get('/crawler/sources', { params })
}

export const getCrawlerSourceDetail = (id: string): Promise<ApiResponse<CrawlerSource>> => {
  return adminClient.get(`/crawler/sources/${id}`)
}

export const createCrawlerSource = (data: Record<string, unknown>): Promise<ApiResponse<{ id: string }>> => {
  return adminClient.post('/crawler/sources', data)
}

export const initializeDefaultCrawlerSources = (): Promise<ApiResponse<{ items: CrawlerSource[]; total: number }>> => {
  return adminClient.post('/crawler/sources/defaults')
}

export const updateCrawlerSource = (id: string, data: Record<string, unknown>): Promise<ApiResponse<{ id: string }>> => {
  return adminClient.put(`/crawler/sources/${id}`, data)
}

export const deleteCrawlerSource = (id: string): Promise<ApiResponse<null>> => {
  return adminClient.delete(`/crawler/sources/${id}`)
}

export const checkSourceHealth = (id: string): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.post(`/crawler/sources/${id}/health`)
}

export const getSourceStats = (id: string, days = 30): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get(`/crawler/sources/${id}/stats`, { params: { days } })
}

// ===== 爬虫统计 =====

export const getCrawlerStatsOverview = (): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/crawler/stats/overview')
}

export const getCrawlerStatsTrend = (days = 7): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/crawler/stats/trend', { params: { days } })
}

export const getCrawlerStatsSources = (days = 7): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/crawler/stats/sources', { params: { days } })
}

export const getCrawlerStatsEfficiency = (days = 7): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/crawler/stats/efficiency', { params: { days } })
}

export const getCrawlerStatsSuggestions = (days = 7): Promise<ApiResponse<Record<string, unknown>[]>> => {
  return adminClient.get('/crawler/stats/suggestions', { params: { days } })
}

// ===== 定时任务 =====

export interface CrawlerScheduleParams {
  page?: number
  page_size?: number
  is_enabled?: boolean
}

export const getCrawlerSchedules = (
  params?: CrawlerScheduleParams
): Promise<ApiResponse<PaginatedResponse<CrawlerSchedule>>> => {
  return adminClient.get('/crawler/schedules', { params })
}

export const getCrawlerScheduleDetail = (id: string): Promise<ApiResponse<CrawlerSchedule>> => {
  return adminClient.get(`/crawler/schedules/${id}`)
}

export const createCrawlerSchedule = (data: Record<string, unknown>): Promise<ApiResponse<{ id: string }>> => {
  return adminClient.post('/crawler/schedules', data)
}

export const updateCrawlerSchedule = (id: string, data: Record<string, unknown>): Promise<ApiResponse<{ id: string }>> => {
  return adminClient.put(`/crawler/schedules/${id}`, data)
}

export const deleteCrawlerSchedule = (id: string): Promise<ApiResponse<null>> => {
  return adminClient.delete(`/crawler/schedules/${id}`)
}

export const toggleCrawlerSchedule = (id: string, enabled: boolean): Promise<ApiResponse<{ id: string; is_enabled: boolean }>> => {
  return adminClient.post(`/crawler/schedules/${id}/toggle`, null, { params: { enabled } })
}

export const getScheduleRuns = (
  id: string,
  params?: { page?: number; page_size?: number; status?: string }
): Promise<ApiResponse<PaginatedResponse<Record<string, unknown>>>> => {
  return adminClient.get(`/crawler/schedules/${id}/runs`, { params })
}

// ===== 爬虫日志 =====

export interface CrawlerLogParams {
  task_id?: string
  source_id?: string
  level?: string
  status?: string
  resource_type?: string
  start_time?: string
  end_time?: string
  page?: number
  page_size?: number
}

export const getCrawlerLogs = (
  params?: CrawlerLogParams
): Promise<ApiResponse<PaginatedResponse<CrawlerLog>>> => {
  return adminClient.get('/crawler/logs', { params })
}

export const exportCrawlerLogs = (
  params?: CrawlerLogParams,
  format: 'csv' | 'json' = 'csv'
): Promise<Blob> => {
  return adminClient.get('/crawler/logs/export', {
    params: { ...params, format },
    responseType: 'blob',
  }) as unknown as Promise<Blob>
}

export const getCrawlerLogAnalysis = (days = 7): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/crawler/logs/analysis', { params: { days } })
}

// ===== 爬虫配置 =====

export interface CrawlerRuntimeConfig {
  concurrent_requests: number
  concurrent_requests_per_domain: number
  download_delay_seconds: number
  request_timeout_seconds: number
  retry_times: number
  rotate_user_agent: boolean
  user_agent: string
  obey_robots_txt: boolean
  follow_redirects: boolean
  max_redirect_times: number
  max_depth: number
  proxy_enabled: boolean
  proxy_url: string
  log_level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
}

export const getCrawlerConfig = (): Promise<ApiResponse<CrawlerRuntimeConfig>> => {
  return adminClient.get('/crawler/config')
}

export const updateCrawlerConfig = (
  data: CrawlerRuntimeConfig,
): Promise<ApiResponse<CrawlerRuntimeConfig>> => {
  return adminClient.put('/crawler/config', data)
}

// ===== 已下载文件 =====

export interface DownloadedFileParams {
  page?: number
  page_size?: number
  file_type?: string
  status?: string
  task_id?: string
  keyword?: string
}

export const getDownloadedFiles = (
  params?: DownloadedFileParams
): Promise<ApiResponse<PaginatedResponse<DownloadedFile>>> => {
  return adminClient.get('/files/downloaded', { params })
}

export const getDownloadedFileDetail = (id: string): Promise<ApiResponse<DownloadedFile>> => {
  return adminClient.get(`/files/downloaded/${id}`)
}

export const getDownloadedFilePreviewUrl = (id: string): string => {
  return `/api/v1/admin/files/downloaded/${id}/preview`
}
