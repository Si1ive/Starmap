import adminClient from './client'
import type { ApiResponse, Conversation, PaginatedResponse } from '@/types'

export interface ConversationParams {
  page?: number
  page_size?: number
  q?: string
  start_date?: string
  end_date?: string
}

export const getConversations = (
  params?: ConversationParams
): Promise<ApiResponse<PaginatedResponse<Conversation>>> => {
  return adminClient.get('/conversations', { params })
}

export const getConversationDetail = (id: string): Promise<ApiResponse<Conversation>> => {
  return adminClient.get(`/conversations/${id}`)
}

export const deleteConversation = (id: string): Promise<ApiResponse<{ deleted: number }>> => {
  return adminClient.delete(`/conversations/${id}`)
}

export const getConversationStats = (): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/conversations/stats')
}
