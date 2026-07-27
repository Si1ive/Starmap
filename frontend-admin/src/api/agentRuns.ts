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

export interface AdminAgentSessionDetail extends Omit<
  AdminAgentSession,
  'latest_workflow_key' | 'current_step_key'
> {
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

export interface AdminMemorySnapshotItem {
  id: number
  snapshot_id: string
  memory_need: string
  memory_partition: string
  source_kind: string
  source_id: string | null
  item_key: string
  version: number | null
  selected: boolean
  selection_reason: string | null
  dropped_reason: string | null
  token_estimate: number
  frozen_payload: Record<string, unknown>
  source_lookup_supported: boolean
  created_at: string
}

export interface AdminRunMemoryObservability {
  run: {
    id: string
    thread_id: string
    user_id: string
    workflow_key: string
    status: string
    raw_input: string | null
  }
  turn_understanding: Record<string, unknown>
  snapshot: {
    id: string
    state_version: number
    standalone_request: string | null
    selection_metadata: Record<string, unknown>
    memory_needs: string[]
    created_at: string
  } | null
  items: AdminMemorySnapshotItem[]
  token_budget: {
    configured: number | null
    context_estimated: number | null
    selected_items: number
    dropped_items: number
  }
  model: {
    config_id: string | null
    name: string | null
    provider: string | null
    model_call_count: number
    max_model_calls: number
    final_model_call_id: string | null
    calls: Record<string, unknown>[]
  }
  tool_calls: Record<string, unknown>[]
  memory_outbox: Array<{
    id: number
    event_type: string
    task_key: string | null
    status: string
    retry_count: number
    safe_error_summary: string | null
    scheduled_at: string
    processed_at: string | null
    created_at: string
  }>
  memory_trace: AdminMemoryTrace[]
}

export interface AdminMemoryTrace {
  id: number
  event_id: number | null
  event_sequence: number | null
  event_type: string
  changed: boolean
  before: Record<string, unknown>
  after: Record<string, unknown>
  created_at: string
}

export interface AdminRunMemoryReplay {
  mode: 'frozen_snapshot_read_only'
  run: AdminRunMemoryObservability['run']
  turn_understanding: Record<string, unknown>
  snapshot: NonNullable<AdminRunMemoryObservability['snapshot']>
  ordered_items: AdminMemorySnapshotItem[]
  token_budget: AdminRunMemoryObservability['token_budget']
  model: AdminRunMemoryObservability['model']
  actual_tool_calls: Record<string, unknown>[]
}

export interface AdminMemorySourceComparison {
  run_id: string
  snapshot_id: string
  item_id: number
  source_kind: string
  source_id: string | null
  frozen_version: number | null
  current_version: number | null
  superseded: boolean
  frozen_copy: Record<string, unknown>
  current_source: Record<string, unknown>
}

export interface AdminMemoryOutbox {
  id: number
  run_id: string | null
  thread_id: string
  user_id: string
  event_type: string
  task_key: string | null
  status: 'pending' | 'processing' | 'completed' | 'failed'
  retry_count: number
  worker_id: string | null
  safe_error_summary: string | null
  scheduled_at: string
  processed_at: string | null
  created_at: string
  replay_allowed: boolean
  replay_block_reason: string | null
  payload?: Record<string, unknown>
}

export interface MemoryOutboxParams {
  page?: number
  page_size?: number
  event_type?: string
  status?: string
  run_id?: string
  thread_id?: string
  source_id?: string
  start_date?: string
  end_date?: string
}

export const getAgentRuns = (
  params?: AgentRunsParams
): Promise<ApiResponse<PaginatedResponse<AdminAgentSession>>> => {
  return adminClient.get('/agent-runs', { params })
}

export const getAgentRunDetail = (
  identifier: string
): Promise<ApiResponse<AdminAgentSessionDetail>> => {
  return adminClient.get(`/agent-runs/${identifier}`)
}

export const replayAgentRun = (
  runId: string
): Promise<ApiResponse<{ eval_run_id: string; message: string }>> => {
  return adminClient.post(`/agent-runs/${runId}/replay`)
}

export const getAgentRunStats = (): Promise<ApiResponse<Record<string, unknown>>> => {
  return adminClient.get('/agent-runs/stats')
}

export const getAgentRunMemory = (
  runId: string
): Promise<ApiResponse<AdminRunMemoryObservability>> => {
  return adminClient.get(`/agent-runs/${runId}/memory`)
}

export const replayAgentRunMemory = (runId: string): Promise<ApiResponse<AdminRunMemoryReplay>> => {
  return adminClient.get(`/agent-runs/${runId}/memory-replay`)
}

export const getAgentRunMemorySource = (
  runId: string,
  itemId: number
): Promise<ApiResponse<AdminMemorySourceComparison>> => {
  return adminClient.get(`/agent-runs/${runId}/memory-sources/${itemId}`)
}

export const getMemoryOutbox = (
  params?: MemoryOutboxParams
): Promise<ApiResponse<PaginatedResponse<AdminMemoryOutbox>>> => {
  return adminClient.get('/agent-runs/memory-outbox', { params })
}

export const getMemoryOutboxDetail = (
  outboxId: number
): Promise<ApiResponse<AdminMemoryOutbox>> => {
  return adminClient.get(`/agent-runs/memory-outbox/${outboxId}`)
}

export const replayMemoryOutbox = (outboxId: number): Promise<ApiResponse<AdminMemoryOutbox>> => {
  return adminClient.post(`/agent-runs/memory-outbox/${outboxId}/replay`)
}
