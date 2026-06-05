import adminClient from './client'
import type { ApiResponse, Work, PaginatedResponse } from '@/types'

export interface WorkListParams {
  page?: number
  page_size?: number
  q?: string
  type?: string
  year?: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

export const getWorkList = (
  params?: WorkListParams
): Promise<ApiResponse<PaginatedResponse<Work>>> => {
  return adminClient.get('/works', { params })
}

export const getWorkDetail = (id: string): Promise<ApiResponse<Work>> => {
  return adminClient.get(`/works/${id}`)
}

export const createWork = (data: Partial<Work>): Promise<ApiResponse<Work>> => {
  return adminClient.post('/works', data)
}

export const updateWork = (id: string, data: Partial<Work>): Promise<ApiResponse<Work>> => {
  return adminClient.put(`/works/${id}`, data)
}

export const deleteWork = (id: string): Promise<ApiResponse<null>> => {
  return adminClient.delete(`/works/${id}`)
}
