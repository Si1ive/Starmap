/**
 * Agent 对话 API 客户端
 *
 * 与 backend/app/modules/agent/router.py 的 API 对应。
 */

const API_BASE = '/api/v1'

export interface Thread {
  id: string
  user_id: string
  title: string | null
  status: 'active' | 'archived' | 'deleted'
  metadata?: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface Run {
  id: string
  thread_id: string
  workflow_name: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'waiting_for_user' | 'waiting_for_approval'
  input_message: string
  result_artifact_id: string | null
  error_message: string | null
  model_call_count: number
  created_at: string
  updated_at: string
}

export interface AgentEvent {
  id: number
  run_id: string
  sequence: number
  event_type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface Artifact {
  id: string
  run_id: string
  artifact_type: 'explanation' | 'practice' | 'feedback' | 'plan' | 'message'
  content: Record<string, unknown>
  metadata?: Record<string, unknown> | null
  created_at: string
}

export const RUN_EVENT_TYPES = [
  'run.created',
  'run.status_changed',
  'run.completed',
  'run.failed',
  'step.started',
  'step.completed',
  'step.failed',
  'message.delta',
  'message.completed',
  'artifact.rendered',
  'tool.called',
  'tool.result',
] as const

export type RunEventType = (typeof RUN_EVENT_TYPES)[number]

export interface CreateThreadRequest {
  title?: string
  metadata?: Record<string, unknown>
}

export interface CreateRunRequest {
  thread_id: string
  workflow_name: string
  input_message: string
  client_idempotency_key?: string
  metadata?: Record<string, unknown>
}

export interface Approval {
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

export interface SubmitInputRequest {
  run_id: string
  input_text: string
}

class AgentApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'AgentApiError'
    this.status = status
  }
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`
  const response = await fetch(url, {
    ...(init || {}),
    credentials: 'include',
    headers: {
      ...(init?.headers || {}),
      ...(init?.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
  })

  if (!response.ok) {
    const text = await response.text().catch(() => 'Unknown error')
    throw new AgentApiError(text, response.status)
  }

  const data = (await response.json().catch(() => null)) as T
  return data
}

// ==================== Thread API ====================

export async function createThread(req: CreateThreadRequest): Promise<Thread> {
  return apiRequest<Thread>('/agent/threads', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export async function listThreads(limit = 20, offset = 0): Promise<{ items: Thread[]; total: number }> {
  return apiRequest<{ items: Thread[]; total: number }>(`/agent/threads?limit=${limit}&offset=${offset}`)
}

export async function getThread(threadId: string): Promise<Thread> {
  return apiRequest<Thread>(`/agent/threads/${threadId}`)
}


// ==================== Thread Runs API ====================

export async function listThreadRuns(threadId: string): Promise<{ items: Run[]; total: number }> {
  return apiRequest<{ items: Run[]; total: number }>(`/agent/threads/${threadId}/runs`)
}

// ==================== Run API ====================

export async function createRun(req: CreateRunRequest): Promise<Run> {
  return apiRequest<Run>('/agent/runs', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export async function getRun(runId: string): Promise<Run> {
  return apiRequest<Run>(`/agent/runs/${runId}`)
}

export async function submitInput(runId: string, inputText: string): Promise<SubmitInputRequest> {
  return apiRequest<SubmitInputRequest>(`/agent/runs/${runId}/submit`, {
    method: 'POST',
    body: JSON.stringify({ input_text: inputText }),
  })
}

// ==================== Events API ====================

export async function getRunEvents(
  runId: string,
  afterSequence = 0,
  limit = 100,
): Promise<{ run_id: string; events: AgentEvent[]; total: number }> {
  return apiRequest<{ run_id: string; events: AgentEvent[]; total: number }>(
    `/agent/runs/${runId}/events?after_sequence=${afterSequence}&limit=${limit}`,
  )
}

export function createEventSource(runId: string, afterSequence = 0): EventSource {
  return new EventSource(`${API_BASE}/agent/runs/${runId}/events/stream?after_sequence=${afterSequence}`, {
    withCredentials: true,
  })
}

export function listenToRunEvents(
  source: EventSource,
  runId: string,
  onEvent: (event: AgentEvent) => void,
): () => void {
  const listeners = RUN_EVENT_TYPES.map((eventType) => {
    const listener = (event: Event) => {
      const message = event as MessageEvent<string>
      if (!message.data) return

      try {
        const sequence = Number(message.lastEventId)
        if (!Number.isFinite(sequence) || sequence <= 0) return
        onEvent({
          id: sequence,
          run_id: runId,
          sequence,
          event_type: eventType,
          payload: JSON.parse(message.data) as Record<string, unknown>,
          created_at: new Date().toISOString(),
        })
      } catch {
        // 单条非法事件不应中断后续事件流。
      }
    }
    source.addEventListener(eventType, listener)
    return { eventType, listener }
  })

  return () => {
    for (const { eventType, listener } of listeners) {
      source.removeEventListener(eventType, listener)
    }
  }
}

// ==================== Artifacts API ====================

export async function getRunArtifacts(runId: string): Promise<{ run_id: string; artifacts: Artifact[] }> {
  return apiRequest<{ run_id: string; artifacts: Artifact[] }>(`/agent/runs/${runId}/artifacts`)
}

// ==================== Approval API ====================

export async function getRunApprovals(runId: string): Promise<{ run_id: string; approvals: Approval[] }> {
  return apiRequest<{ run_id: string; approvals: Approval[] }>(`/agent/runs/${runId}/approvals`)
}

export async function approveApproval(runId: string, approvalId: string): Promise<Approval> {
  return apiRequest<Approval>(`/agent/runs/${runId}/approvals/${approvalId}/approve`, {
    method: 'POST',
  })
}

export async function rejectApproval(runId: string, approvalId: string): Promise<Approval> {
  return apiRequest<Approval>(`/agent/runs/${runId}/approvals/${approvalId}/reject`, {
    method: 'POST',
  })
}
