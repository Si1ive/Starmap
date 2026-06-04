import adminClient from './client'
import type { ApiResponse, CrawlerTask, PaginatedResponse } from '@/types'

export interface CrawlerTaskParams {
  page?: number
  page_size?: number
  status?: string
  type?: string
}

export const getCrawlerTasks = (
  params?: CrawlerTaskParams
): Promise<ApiResponse<PaginatedResponse<CrawlerTask>>> => {
  return adminClient.get('/crawler/tasks', { params })
}

export const createCrawlerTask = (data: Partial<CrawlerTask>): Promise<ApiResponse<CrawlerTask>> => {
  return adminClient.post('/crawler/tasks', data)
}

export const stopCrawlerTask = (id: string): Promise<ApiResponse<CrawlerTask>> => {
  return adminClient.post(`/crawler/tasks/${id}/stop`)
}

export const getCrawlerLogs = (id: string): Promise<ApiResponse<string[]>> => {
  return adminClient.get(`/crawler/tasks/${id}/logs`)
}

export const getCrawlerConfig = (): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/crawler/config')
}

export const updateCrawlerConfig = (data: Record<string, unknown>): Promise<ApiResponse<null>> => {
  return adminClient.put('/crawler/config', data)
}
