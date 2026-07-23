import adminClient from './client'
import type { ApiResponse, PaginatedResponse } from '@/types'

export interface AdminAgentRun {
  id: string
  thread_id: string
  user_id: string
  workflow_key: string
  workflow_version: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'waiting_for_user' | 'waiting_for_approval'
  request_id: string
  current_step_key: string | null
  last_event_sequence: number
  lease_owner: string | null
  lease_expires_at: string | null
  model_config_id: string | null
  started_at: string | null
  completed_at: string | null
  error_code: string | null
  safe_error_summary: string | null
  created_at: string
  updated_at: string
}

export interface AdminAgentRunEvent {
  id: number
  run_id: string
  sequence: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface AgentRunsParams {
  page?: number
  page_size?: number
  status?: string
  workflow_key?: string
  start_date?: string
  end_date?: string
  user_id?: string
}


export interface AdminAgentRunApproval {
  id: string
  run_id: string
  action_key: string
  status: 'pending' | 'approved' | 'rejected' | 'expired'
  diff_ref: string | null
  precondition_ref: string | null
  decided_by: string | null
  expires_at: string | null
  created_at: string
  updated_at: string
}

export const getAgentRunApprovals = (runId: string): Promise<ApiResponse<{ run_id: string; approvals: AdminAgentRunApproval[] }>> => {
  return adminClient.get(`/agent-runs/${runId}/approvals`)
}

export const approveApproval = (runId: string, approvalId: string): Promise<ApiResponse<{ id: string; status: string; message: string }>> => {
  return adminClient.post(`/agent-runs/${runId}/approvals/${approvalId}/approve`)
}

export const rejectApproval = (runId: string, approvalId: string): Promise<ApiResponse<{ id: string; status: string; message: string }>> => {
  return adminClient.post(`/agent-runs/${runId}/approvals/${approvalId}/reject`)
}

export const getAgentRuns = (
  params?: AgentRunsParams,
): Promise<ApiResponse<PaginatedResponse<AdminAgentRun>>> => {
  return adminClient.get('/agent-runs', { params })
}

export const getAgentRunDetail = (runId: string): Promise<ApiResponse<AdminAgentRun>> => {
  return adminClient.get(`/agent-runs/${runId}`)
}

export const getAgentRunEvents = (runId: string): Promise<ApiResponse<{ run_id: string; events: AdminAgentRunEvent[]; total: number }>> => {
  return adminClient.get(`/agent-runs/${runId}/events`)
}

export const replayAgentRun = (runId: string): Promise<ApiResponse<{ eval_run_id: string }>> => {
  return adminClient.post(`/agent-runs/${runId}/replay`)
}

export const getAgentRunStats = (): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/agent-runs/stats')
}
