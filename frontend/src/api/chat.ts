import apiClient from './client'

export interface ChatRequest {
  message: string
  session_id?: string
  context?: Record<string, any>
}

export interface ChatResponse {
  session_id: string
  message: string
  type: string
  sources: Array<{
    type: string
    entity: string
    relation?: string
  }>
  suggestions: string[]
}

export const sendMessage = (data: ChatRequest) => {
  return apiClient.post<ChatResponse>('/chat', data)
}

export const getChatHistory = (sessionId: string) => {
  return apiClient.get(`/chat/${sessionId}/history`)
}
