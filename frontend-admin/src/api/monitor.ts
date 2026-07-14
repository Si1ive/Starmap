import adminClient from './client'
import type { ApiResponse } from '@/types'

export interface ApiLatencyStats {
  p50: number | null
  p95: number
  p99: number | null
  sample_count: number
  coverage_percent: number
}

export interface ApiEndpointMetric {
  endpoint: string
  method: string
  calls: number
  avg_latency: number
  max_latency: number
  p95: number
  error_rate: number
}

export interface ApiMonitorData {
  window_hours: number
  total_requests: number
  avg_latency: number
  error_rate: number
  qps: number
  latency_stats: ApiLatencyStats
  endpoints: ApiEndpointMetric[]
  slow_queries: ApiEndpointMetric[]
  qps_trend: Array<{ date: string; count: number }>
}

export const getApiMonitor = (hours = 24): Promise<ApiResponse<ApiMonitorData>> => {
  return adminClient.get('/monitor/api', { params: { hours } })
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

export const getLLMCallStats = (hours = 24): Promise<ApiResponse<LLMCallStats>> => {
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

// ===== 服务日志（替换原 errors 接口的能力） =====

export interface ServiceLogItem {
  id: number
  level: string
  logger_name?: string
  event?: string
  message?: string
  request_id?: string
  context?: Record<string, unknown>
  traceback?: string
  created_at: string
}

export const getServiceLogs = (params?: {
  level?: string
  logger_name?: string
  keyword?: string
  request_id?: string
  start_time?: string
  end_time?: string
  page?: number
  page_size?: number
}): Promise<ApiResponse<{ total: number; page: number; page_size: number; items: ServiceLogItem[] }>> => {
  return adminClient.get('/monitor/logs', { params })
}

export const getServiceLogStats = (hours = 24): Promise<ApiResponse<{
  window_hours: number
  by_level: Array<{ level: string; count: number }>
  top_loggers: Array<{ logger: string; count: number }>
}>> => {
  return adminClient.get('/monitor/logs/stats', { params: { hours } })
}

export const deleteServiceLogs = (params: { older_than_days?: number; level?: string }): Promise<ApiResponse<{ deleted: number }>> => {
  return adminClient.delete('/monitor/logs', { params })
}

export const archiveServiceLogs = (older_than_days: number): Promise<ApiResponse<{ archived: number; deleted: number; path: string | null }>> => {
  return adminClient.post('/monitor/logs/archive', null, { params: { older_than_days } })
}

// ===== 系统资源 =====

export interface SystemMetricSample {
  cpu_percent: number
  mem_used_mb: number
  mem_total_mb: number
  mem_percent: number
  disk_used_gb: number
  disk_total_gb: number
  disk_percent: number
  process_rss_mb: number
  process_cpu_percent: number
  sampled_at: string
}

export const getSystemMetrics = (hours = 24): Promise<ApiResponse<{
  latest: SystemMetricSample | null
  series: SystemMetricSample[]
  window_hours: number
}>> => {
  return adminClient.get('/monitor/system', { params: { hours } })
}

// ===== 向量召回日志 =====

export interface VectorRecallTopResult {
  rank: number
  chapter_id?: string
  chapter_name?: string | null
  score: number
  is_primary: boolean
}

export interface VectorRecallItem {
  id: string
  called_by?: string
  purpose?: string
  query_text?: string
  query_entity_id?: string
  subject_id?: string
  top_results: VectorRecallTopResult[]
  top_score: number
  result_count: number
  threshold_hit: boolean
  latency_ms: number
  status: string
  error_msg?: string
  created_at?: string
}

export interface VectorRecallStats {
  window_hours: number
  total_recalls: number
  hit_count: number
  miss_count: number
  error_count: number
  hit_rate: number
  threshold_hit_rate: number
  avg_top_score: number
  avg_latency_ms: number
  p95_latency_ms: number
}

export const listVectorRecalls = (params: {
  page?: number
  page_size?: number
  called_by?: string
  status?: string
  keyword?: string
}): Promise<ApiResponse<{ total: number; page: number; page_size: number; items: VectorRecallItem[] }>> => {
  return adminClient.get('/monitor/vector-recalls', { params })
}

export const getVectorRecallStats = (hours = 24): Promise<ApiResponse<VectorRecallStats>> => {
  return adminClient.get('/monitor/vector-recalls/stats', { params: { hours } })
}

export const deleteVectorRecalls = (params: {
  older_than_days?: number
}): Promise<ApiResponse<{ deleted: number }>> => {
  return adminClient.delete('/monitor/vector-recalls', { params })
}
