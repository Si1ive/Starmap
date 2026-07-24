import adminClient from './client'
import type { ApiResponse, PaginatedResponse } from '@/types'

export type AgentRunStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'waiting_for_user'
  | 'waiting_for_approval'

export interface AdminAgentSession {
  id: string
  thread_id: string
  title: string
  user_id: string
  thread_status: 'active' | 'archived' | 'deleted'
  latest_status: AgentRunStatus
  latest_workflow_key: string | null
  current_step_key: string | null
  turn_count: number
  total_run_count: number
  event_count: number
  created_at: string
  updated_at: string
}

export interface AdminAgentRun {
  id: string
  thread_id: string
  user_id: string
  workflow_key: string
  workflow_version: string
  status: AgentRunStatus
  input_message: string | null
  trigger_message_id: string | null
  parent_run_id: string | null
  root_run_id: string
  presentation: string
  public_title: string | null
  public_summary: string | null
  current_step_key: string | null
  event_count: number
  model_config_id: string | null
  error_code: string | null
  safe_error_summary: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface AdminAgentMessage {
  id: string
  run_id: string | null
  role: 'user' | 'assistant' | 'system'
  status: 'pending' | 'streaming' | 'completed' | 'failed'
  content: string
  error_code: string | null
  created_at: string
  completed_at: string | null
}

export interface AdminAgentRunEvent {
  id: number
  run_id: string
  sequence: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string
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

export interface AdminAgentRunArtifact {
  id: string
  run_id: string
  type: string
  content: Record<string, unknown>
  metadata: Record<string, unknown>
  created_at: string
}

export interface AdminAgentTurn {
  turn_number: number
  root_run_id: string
  status: AgentRunStatus
  input_message: string
  user_message: AdminAgentMessage | null
  assistant_messages: AdminAgentMessage[]
  runs: AdminAgentRun[]
  events: AdminAgentRunEvent[]
  approvals: AdminAgentRunApproval[]
  artifacts: AdminAgentRunArtifact[]
  created_at: string
  completed_at: string | null
}

export interface AdminAgentSessionDetail
  extends Omit<AdminAgentSession, 'latest_workflow_key' | 'current_step_key'> {
  turns: AdminAgentTurn[]
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

export const getAgentRuns = (
  params?: AgentRunsParams,
): Promise<ApiResponse<PaginatedResponse<AdminAgentSession>>> => {
  return adminClient.get('/agent-runs', { params })
}

export const getAgentRunDetail = (
  identifier: string,
): Promise<ApiResponse<AdminAgentSessionDetail>> => {
  return adminClient.get(`/agent-runs/${identifier}`)
}

export const replayAgentRun = (
  runId: string,
): Promise<ApiResponse<{ eval_run_id: string; message: string }>> => {
  return adminClient.post(`/agent-runs/${runId}/replay`)
}

export const getAgentRunStats = (): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/agent-runs/stats')
}
