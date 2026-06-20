import adminClient from './client'
import type { ApiResponse } from '@/types'

export interface PdfParserRuntimeStatus {
  parser_name: 'docling' | 'mineru'
  parser_version: string
  health_status: 'ready' | 'unavailable'
  is_available: boolean
  is_active: boolean
  checked_at: string
  deployment_target?: 'local' | 'remote'
  service_endpoint?: string
  error_detail?: string | null
}

export interface LlmConfig {
  enabled: boolean
  provider: 'openai_compatible'
  base_url: string
  api_key: string
  model: string
  temperature: number
  max_tokens: number
  timeout_seconds: number
  system_prompt: string
}

export interface EmbeddingConfig {
  enabled: boolean
  provider: 'openai_compatible'
  base_url: string
  api_key: string
  model: string
  dimension: number
  timeout_seconds: number
}

export interface SystemSettings {
  llm: LlmConfig
  pdf_structure_llm: LlmConfig
  outline_llm: LlmConfig
  doc_meta_llm: LlmConfig
  enrich_llm: LlmConfig
  embedding: EmbeddingConfig
  pdf_parser: {
    active_parser: 'docling' | 'mineru'
    service_mode: 'single_active'
    service_switch_notes: string
    deployment_target: 'local' | 'remote'
    local_service_endpoint: string
    remote_service_endpoint: string
    request_timeout_seconds: number
    processing_window_size: number
    active_runtime_status?: PdfParserRuntimeStatus | null
    available_parsers?: PdfParserRuntimeStatus[]
  }
}

// 对话型 LLM 配置块的 kind
export type LlmKind = 'llm' | 'pdf_structure_llm' | 'outline_llm' | 'doc_meta_llm' | 'enrich_llm' | 'embedding'

export const getSettings = (): Promise<ApiResponse<SystemSettings>> => {
  return adminClient.get('/settings')
}

export const updateSettings = (data: Partial<SystemSettings>): Promise<ApiResponse<SystemSettings>> => {
  return adminClient.put('/settings', data)
}

export interface LlmStatus {
  enabled: boolean
  provider: string
  model: string
  base_url: string
  dimension?: number
  has_api_key: boolean
  uses_env_api_key: boolean
  is_available: boolean
  issues: string[]
}

export interface LlmTestResult {
  success: boolean
  provider?: string
  model: string
  base_url?: string
  reply?: string
  dimension?: number
  configured_dimension?: number
  dimension_match?: boolean
  error?: string
}

export const getLlmStatus = (kind: LlmKind): Promise<ApiResponse<LlmStatus>> => {
  return adminClient.get(`/settings/llm/${kind}/status`)
}

export const testLlm = (
  kind: LlmKind,
  data: Partial<LlmConfig & EmbeddingConfig>,
): Promise<ApiResponse<LlmTestResult>> => {
  return adminClient.post(`/settings/llm/${kind}/test`, data, { timeout: 120000 })
}

export interface PdfParserSwitchHistoryItem {
  id: number
  old_parser: string | null
  new_parser: string | null
  old_target: 'local' | 'remote' | null
  new_target: 'local' | 'remote' | null
  switch_notes: string
  user_id: string | null
  created_at: string
}

export const getPdfParserHistory = (
  page: number = 1,
  pageSize: number = 20,
): Promise<ApiResponse<{ items: PdfParserSwitchHistoryItem[]; total: number; page: number; page_size: number }>> => {
  return adminClient.get('/settings/pdf-parser/history', { params: { page, page_size: pageSize } })
}
