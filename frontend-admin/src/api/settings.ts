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

export interface SystemSettings {
  llm: {
    model: string
    temperature: number
    max_tokens: number
    system_prompt: string
  }
  search: {
    default_page_size: number
    max_results: number
    similarity_threshold: number
    weights: {
      name: number
      category: number
      relation: number
    }
    cache_ttl: number
  }
  crawler: {
    request_interval: number
    max_concurrency: number
    timeout: number
    user_agents: string[]
    proxy?: string
    max_concurrent?: number
    request_delay?: number
    request_timeout?: number
    max_retries?: number
    retry_delay?: number
    user_agent?: string
    proxy_enabled?: boolean
    proxy_url?: string
    respect_robots_txt?: boolean
    auto_detect_encoding?: boolean
    follow_redirects?: boolean
    max_redirects?: number
    max_depth?: number
    dedup_enabled?: boolean
    storage_batch_size?: number
    log_level?: string
    data_sources?: Array<{
      name: string
      url: string
      enabled: boolean
      priority: number
    }>
  }
  system: {
    name: string
    logo?: string
    announcement?: string
    maintenance_mode: boolean
    log_level: string
  }
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

export const getSettings = (): Promise<ApiResponse<SystemSettings>> => {
  return adminClient.get('/settings')
}

export const updateSettings = (data: Partial<SystemSettings>): Promise<ApiResponse<SystemSettings>> => {
  return adminClient.put('/settings', data)
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
