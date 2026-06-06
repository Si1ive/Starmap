import adminClient from './client'
import type { ApiResponse, PaginatedResponse, CrawlerTask, CrawlerSource, CrawlerSchedule, CrawlerLog } from '@/types'

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

export const getCrawlerLogAnalysis = (days = 7): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/crawler/logs/analysis', { params: { days } })
}

// ===== 爬虫配置 (复用 settings API) =====

export const getCrawlerConfig = (): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/crawler/config')
}

export const updateCrawlerConfig = (data: Record<string, unknown>): Promise<ApiResponse<null>> => {
  return adminClient.put('/crawler/config', data)
}
