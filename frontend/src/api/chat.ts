import apiClient from './client'
import type { ChatRetrievalTarget, IChatResponse, IChatHistory } from '@/types'

export interface ChatRequest {
  message: string
  session_id?: string
  context?: Record<string, unknown>
  subject_id?: string
  retrieval_target?: ChatRetrievalTarget
}

// 发送消息 - 直接返回 ChatResponse（后端不包装）
export const sendMessage = async (data: ChatRequest): Promise<IChatResponse> => {
  const response = await apiClient.post('/chat', data)
  return response as unknown as IChatResponse
}

// 获取对话历史 - 直接返回 ChatHistory（后端不包装）
export const getChatHistory = async (sessionId: string): Promise<IChatHistory> => {
  const response = await apiClient.get(`/chat/${sessionId}/history`)
  return response as unknown as IChatHistory
}
