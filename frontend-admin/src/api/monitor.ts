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

// ===== LLM 调用监控 =====

export interface LLMCallSummary {
  id: string
  provider: string
  model: string
  called_by?: string
  purpose?: string
  status: 'success' | 'error' | 'timeout'
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  latency_ms: number
  error_msg?: string
  created_at: string
}

export interface LLMCallDetail extends LLMCallSummary {
  base_url?: string
  request_messages?: Array<{ role: string; content: string }>
  request_params?: Record<string, unknown>
  response_text?: string
  response_full?: Record<string, unknown>
}

export interface LLMCallStats {
  window_hours: number
  total_calls: number
  success_calls: number
  error_calls: number
  error_rate: number
  total_tokens: number
  total_cost_usd: number
  avg_latency_ms: number
  p50_latency_ms: number
  p95_latency_ms: number
  p99_latency_ms: number
  by_model: Array<{ model: string; count: number; tokens: number; cost_usd: number; errors: number }>
}

export const listLLMCalls = (params: {
  page?: number
  page_size?: number
  model?: string
  status?: string
  called_by?: string
  keyword?: string
}): Promise<ApiResponse<{ total: number; page: number; page_size: number; items: LLMCallSummary[] }>> => {
  return adminClient.get('/monitor/llm-calls', { params })
}

export const getLLMCallStats = (hours: number = 24): Promise<ApiResponse<LLMCallStats>> => {
  return adminClient.get('/monitor/llm-calls/stats', { params: { hours } })
}

export const getLLMCallDetail = (id: string): Promise<ApiResponse<LLMCallDetail>> => {
  return adminClient.get(`/monitor/llm-calls/${id}`)
}

export const deleteLLMCalls = (params: {
  older_than_days?: number
  ids?: string
}): Promise<ApiResponse<{ deleted: number }>> => {
  return adminClient.delete('/monitor/llm-calls', { params })
}
