import adminClient from './client'
import type { ApiResponse } from '@/types'

export interface AgentModelConfig {
  id: string
  display_name: string
  provider: 'openai_compatible'
  base_url: string
  api_key: string
  has_api_key: boolean
  model_name: string
  online: boolean
  selectable: boolean
  is_default: boolean
  temperature: number
  max_tokens: number | null
  timeout_seconds: number
  created_at: string | null
  updated_at: string | null
}

export interface AgentModelConfigInput {
  display_name: string
  provider: 'openai_compatible'
  base_url: string
  api_key?: string
  model_name: string
  online: boolean
  selectable: boolean
  is_default: boolean
  temperature: number
  max_tokens: number | null
  timeout_seconds: number
}

export interface AgentModelTestResult {
  success: boolean
  model?: string
  base_url?: string
  reply?: string
  error?: string
}

export const listAgentModels = (): Promise<ApiResponse<{ items: AgentModelConfig[] }>> =>
  adminClient.get('/agent-models')

export const createAgentModel = (
  input: AgentModelConfigInput,
): Promise<ApiResponse<AgentModelConfig>> => adminClient.post('/agent-models', input)

export const updateAgentModel = (
  id: string,
  input: Partial<AgentModelConfigInput>,
): Promise<ApiResponse<AgentModelConfig>> => adminClient.put(`/agent-models/${id}`, input)

export const updateAgentModelAvailability = (
  id: string,
  input: Pick<AgentModelConfig, 'online' | 'selectable'>,
): Promise<ApiResponse<AgentModelConfig>> =>
  adminClient.put(`/agent-models/${id}/availability`, input)

export const setDefaultAgentModel = (id: string): Promise<ApiResponse<AgentModelConfig>> =>
  adminClient.post(`/agent-models/${id}/default`)

export const testAgentModel = (id: string): Promise<ApiResponse<AgentModelTestResult>> =>
  adminClient.post(`/agent-models/${id}/test`, undefined, { timeout: 120000 })
