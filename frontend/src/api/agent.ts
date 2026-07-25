/**
 * Agent 对话 API 客户端
 *
 * 与 backend/app/modules/agent/router.py 的 API 对应。
 */

const API_BASE = '/api/v1'
const APP_AGENT_BASE = '/app/agent'

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
  status:
    | 'queued'
    | 'running'
    | 'completed'
    | 'failed'
    | 'waiting_for_user'
    | 'waiting_for_approval'
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

export type MessageRole = 'user' | 'assistant' | 'system'
export type MessageStatus = 'pending' | 'streaming' | 'completed' | 'failed'
export type TimelineItemType = 'message' | 'workflow' | 'notice'

export interface MessageView {
  id: string
  role: MessageRole
  status: MessageStatus
  content: string | null
  content_blocks: Record<string, unknown>[]
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface WorkflowProgressView {
  completed: number
  total: number
}

export interface WorkflowStepView {
  id: string
  label: string
  status: string
  started_at: string | null
  completed_at: string | null
}

export interface WorkflowInputView {
  id: string
  run_id: string
  input_key: string
  status: 'pending' | 'answered' | 'expired'
  question: string
  schema: Record<string, unknown>
  expires_at: string | null
}

export interface WorkflowApprovalView {
  id: string
  run_id: string
  action_key: string
  status: 'pending' | 'approved' | 'rejected' | 'expired'
  change: Record<string, unknown>
  expires_at: string | null
}

export interface WorkflowArtifactView {
  id: string
  type: string
  title: string
  summary: unknown
  content: Record<string, unknown>
  actions: Record<string, unknown>[]
  created_at: string
}

export interface WorkflowActivityView {
  id: string
  activity_type: string
  title: string
  detail: string | null
  status: string
  metadata: Record<string, unknown>
  started_at: string
  completed_at: string | null
}

export interface WorkflowView {
  root_run_id: string
  status: string
  title: string
  summary: string | null
  current_step: string | null
  progress: WorkflowProgressView
  steps: WorkflowStepView[]
  activities: WorkflowActivityView[]
  pending_input: WorkflowInputView | null
  pending_approval: WorkflowApprovalView | null
  artifacts: WorkflowArtifactView[]
  created_at: string
  updated_at: string
}

export interface TimelineItem {
  id: string
  sequence: number
  type: TimelineItemType
  message: MessageView | null
  workflow: WorkflowView | null
  notice: Record<string, unknown> | null
  created_at: string
}

export interface TimelineThreadView {
  id: string
  title: string | null
  updated_at: string
}

export interface TimelineResponse {
  thread: TimelineThreadView
  items: TimelineItem[]
  previous_cursor: number | null
  latest_cursor: number
  has_more: boolean
}

export interface TurnCreateRequest {
  content: string
  model_config_id?: string
  attachments?: Record<string, unknown>[]
  context_refs?: Record<string, unknown>[]
  client_message_id: string
}

export interface SelectableAgentModel {
  id: string
  display_name: string
  is_default: boolean
}

export interface WorkflowRunView {
  id: string
  status: string
  presentation: string
  public_title: string | null
}

export interface TurnCreateResponse {
  user_message: MessageView
  root_run: WorkflowRunView
  timeline_cursor: number
}

export const THREAD_EVENT_TYPES = [
  'timeline.snapshot',
  'timeline.item.created',
  'message.started',
  'message.delta',
  'message.completed',
  'message.failed',
  'workflow.updated',
  'workflow.input.required',
  'workflow.approval.required',
  'workflow.completed',
  'workflow.failed',
  'workflow.cancelled',
  'workflow.step.updated',
  'workflow.activity.updated',
  'workflow.artifact.created',
] as const

export type ThreadEventType = (typeof THREAD_EVENT_TYPES)[number]

export interface ThreadEvent {
  id: number
  sequence: number
  event_type: ThreadEventType | string
  payload: Record<string, unknown>
  created_at: string
}

export interface ThreadEventsResponse {
  thread_id: string
  events: ThreadEvent[]
  latest_cursor: number
}

export interface ThreadSnapshot {
  latest_sequence: number
  items: TimelineItem[]
  has_more: boolean
}

export interface InputAnswerResponse {
  id: string
  run_id: string
  input_key: string
  status: 'answered'
  message: string
}

export interface ApprovalDecisionResponse {
  id: string
  status: 'approved' | 'rejected'
  message: string
}

export class AgentApiError extends Error {
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
      ...(init?.body !== undefined
        ? { 'Content-Type': 'application/json' }
        : {}),
    },
  })

  if (!response.ok) {
    const text = await response.text().catch(() => '')
    let message = text || '请求失败，请稍后重试'
    try {
      const payload = JSON.parse(text) as { detail?: unknown; message?: unknown }
      if (typeof payload.detail === 'string') message = payload.detail
      else if (typeof payload.message === 'string') message = payload.message
    } catch {
      // 非 JSON 错误响应沿用原始文本。
    }
    throw new AgentApiError(message, response.status)
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

export async function listThreads(
  limit = 20,
  offset = 0,
): Promise<{ items: Thread[]; total: number }> {
  return apiRequest<{ items: Thread[]; total: number }>(
    `/agent/threads?limit=${limit}&offset=${offset}`,
  )
}

export async function getThread(threadId: string): Promise<Thread> {
  return apiRequest<Thread>(`/agent/threads/${threadId}`)
}

// ==================== App Thread Timeline API ====================

export async function listSelectableAgentModels(): Promise<{
  items: SelectableAgentModel[]
}> {
  return apiRequest<{ items: SelectableAgentModel[] }>(`${APP_AGENT_BASE}/models`)
}

export async function createTurn(
  threadId: string,
  req: TurnCreateRequest,
): Promise<TurnCreateResponse> {
  return apiRequest<TurnCreateResponse>(
    `${APP_AGENT_BASE}/threads/${encodeURIComponent(threadId)}/turns`,
    {
      method: 'POST',
      body: JSON.stringify(req),
    },
  )
}

export async function getThreadTimeline(
  threadId: string,
  before?: number,
  limit = 50,
): Promise<TimelineResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (before !== undefined) params.set('before', String(before))
  return apiRequest<TimelineResponse>(
    `${APP_AGENT_BASE}/threads/${encodeURIComponent(threadId)}/timeline?${params.toString()}`,
  )
}

export async function getThreadEvents(
  threadId: string,
  afterSequence = 0,
  limit = 200,
): Promise<ThreadEventsResponse> {
  const params = new URLSearchParams({
    after_sequence: String(afterSequence),
    limit: String(limit),
  })
  return apiRequest<ThreadEventsResponse>(
    `${APP_AGENT_BASE}/threads/${encodeURIComponent(threadId)}/events?${params.toString()}`,
  )
}

export function createThreadEventSource(
  threadId: string,
  afterSequence = 0,
): EventSource {
  const params = new URLSearchParams({ after_sequence: String(afterSequence) })
  return new EventSource(
    `${API_BASE}${APP_AGENT_BASE}/threads/${encodeURIComponent(threadId)}/events/stream?${params.toString()}`,
    { withCredentials: true },
  )
}

export function listenToThreadEvents(
  source: EventSource,
  onEvent: (event: ThreadEvent) => void,
): () => void {
  const listeners = THREAD_EVENT_TYPES.map((eventType) => {
    const listener = (event: Event) => {
      const message = event as MessageEvent<string>
      if (!message.data) return

      try {
        const sequence = Number(message.lastEventId)
        if (!Number.isFinite(sequence) || sequence < 0) return
        onEvent({
          id: sequence,
          sequence,
          event_type: eventType,
          payload: JSON.parse(message.data) as Record<string, unknown>,
          created_at: new Date().toISOString(),
        })
      } catch {
        // 单条非法事件不应中断后续 thread 事件流。
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

// ==================== Thread Runs API ====================

export async function listThreadRuns(
  threadId: string,
): Promise<{ items: Run[]; total: number }> {
  return apiRequest<{ items: Run[]; total: number }>(
    `/agent/threads/${threadId}/runs`,
  )
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

export async function submitInput(
  runId: string,
  inputText: string,
): Promise<SubmitInputRequest> {
  return apiRequest<SubmitInputRequest>(`/agent/runs/${runId}/submit`, {
    method: 'POST',
    body: JSON.stringify({ input_text: inputText }),
  })
}

export async function submitInputAnswer(
  runId: string,
  inputKey: string,
  answer: string,
): Promise<InputAnswerResponse> {
  return apiRequest<InputAnswerResponse>(
    `${APP_AGENT_BASE}/runs/${encodeURIComponent(runId)}/inputs/${encodeURIComponent(inputKey)}/answer`,
    {
      method: 'POST',
      body: JSON.stringify({ answer }),
    },
  )
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

export function createEventSource(
  runId: string,
  afterSequence = 0,
): EventSource {
  return new EventSource(
    `${API_BASE}/agent/runs/${runId}/events/stream?after_sequence=${afterSequence}`,
    {
      withCredentials: true,
    },
  )
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

export async function getRunArtifacts(
  runId: string,
): Promise<{ run_id: string; artifacts: Artifact[] }> {
  return apiRequest<{ run_id: string; artifacts: Artifact[] }>(
    `/agent/runs/${runId}/artifacts`,
  )
}

// ==================== Approval API ====================

export async function getRunApprovals(
  runId: string,
): Promise<{ run_id: string; approvals: Approval[] }> {
  return apiRequest<{ run_id: string; approvals: Approval[] }>(
    `/agent/runs/${runId}/approvals`,
  )
}

export async function approveApproval(
  runId: string,
  approvalId: string,
): Promise<ApprovalDecisionResponse> {
  return apiRequest<ApprovalDecisionResponse>(
    `${APP_AGENT_BASE}/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/approve`,
    {
      method: 'POST',
    },
  )
}

export async function rejectApproval(
  runId: string,
  approvalId: string,
): Promise<ApprovalDecisionResponse> {
  return apiRequest<ApprovalDecisionResponse>(
    `${APP_AGENT_BASE}/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/reject`,
    {
      method: 'POST',
    },
  )
}
