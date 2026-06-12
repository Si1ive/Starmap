import adminClient from './client'
import type { ApiResponse } from '@/types'

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
  }
}

export const getSettings = (): Promise<ApiResponse<SystemSettings>> => {
  return adminClient.get('/settings')
}

export const updateSettings = (data: Partial<SystemSettings>): Promise<ApiResponse<SystemSettings>> => {
  return adminClient.put('/settings', data)
}
