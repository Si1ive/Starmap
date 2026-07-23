/**
 * Agent 状态管理
 *
 * 旧页面仍可使用 run 级状态；新版聊天页通过 normalized thread timeline、
 * thread SSE 与统一 cursor 恢复对话。
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
} from 'react'
import * as agentApi from '../api/agent'
import type { Approval } from '../api/agent'
import {
  initialThreadTimelineState,
  threadTimelineReducer,
  type ThreadTimelineAction,
  type ThreadTimelineState,
} from '../features/agent/timeline-state'

// ==================== Types ====================

export interface Thread {
  id: string
  title: string | null
  status: string
  created_at: string
  updated_at: string
}

export interface Run {
  id: string
  thread_id: string
  workflow_name: string
  status: string
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
}

export interface Artifact {
  id: string
  run_id: string
  artifact_type: string
  content: Record<string, unknown>
  created_at: string
}

export interface AgentState {
  threads: Thread[]
  currentThreadId: string | null
  currentRunId: string | null
  runs: Record<string, Run>
  events: Record<string, AgentEvent[]>
  artifacts: Record<string, Artifact[]>
  approvals: Record<string, Approval[]>
  timeline: ThreadTimelineState
  loading: boolean
  error: string | null
  sseConnected: boolean
}

export type AgentAction =
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'SET_THREADS'; payload: Thread[] }
  | { type: 'SET_CURRENT_THREAD'; payload: string | null }
  | { type: 'SET_CURRENT_RUN'; payload: string | null }
  | { type: 'SET_RUN'; payload: Run }
  | { type: 'SET_RUNS'; payload: Record<string, Run> }
  | { type: 'SET_THREAD_RUNS'; payload: { threadId: string; runs: Run[] } }
  | { type: 'APPEND_EVENTS'; payload: { runId: string; events: AgentEvent[] } }
  | { type: 'SET_ARTIFACTS'; payload: { runId: string; artifacts: Artifact[] } }
  | { type: 'SET_APPROVALS'; payload: { runId: string; approvals: Approval[] } }
  | { type: 'UPDATE_APPROVAL'; payload: { runId: string; approval: Approval } }
  | { type: 'SET_SSE_CONNECTED'; payload: boolean }
  | { type: 'TIMELINE'; payload: ThreadTimelineAction }
  | { type: 'CLEAR_ERROR' }

export interface SendTurnOptions {
  attachments?: Record<string, unknown>[]
  contextRefs?: Record<string, unknown>[]
  preferredAction?: string
  clientMessageId?: string
}

// ==================== Reducer ====================

const initialState: AgentState = {
  threads: [],
  currentThreadId: null,
  currentRunId: null,
  runs: {},
  events: {},
  artifacts: {},
  approvals: {},
  timeline: initialThreadTimelineState,
  loading: false,
  error: null,
  sseConnected: false,
}

function agentReducer(state: AgentState, action: AgentAction): AgentState {
  switch (action.type) {
    case 'SET_LOADING':
      return { ...state, loading: action.payload }
    case 'SET_ERROR':
      return { ...state, error: action.payload }
    case 'SET_THREADS':
      return { ...state, threads: action.payload }
    case 'SET_CURRENT_THREAD':
      return { ...state, currentThreadId: action.payload }
    case 'SET_CURRENT_RUN':
      return { ...state, currentRunId: action.payload }
    case 'SET_RUN':
      return {
        ...state,
        runs: { ...state.runs, [action.payload.id]: action.payload },
      }
    case 'SET_RUNS':
      return { ...state, runs: { ...state.runs, ...action.payload } }
    case 'SET_THREAD_RUNS':
      return {
        ...state,
        runs: {
          ...state.runs,
          ...action.payload.runs.reduce(
            (acc, run) => ({ ...acc, [run.id]: run }),
            {} as Record<string, Run>,
          ),
        },
      }
    case 'APPEND_EVENTS': {
      const currentEvents = state.events[action.payload.runId] || []
      const eventsBySequence = new Map<number, AgentEvent>()
      for (const event of currentEvents)
        eventsBySequence.set(event.sequence, event)
      for (const event of action.payload.events)
        eventsBySequence.set(event.sequence, event)

      const nextEvents = [...eventsBySequence.values()].sort(
        (a, b) => a.sequence - b.sequence,
      )
      const currentRun = state.runs[action.payload.runId]
      let nextRun = currentRun

      if (currentRun) {
        for (const event of action.payload.events) {
          const payload = event.payload as {
            to?: unknown
            error?: unknown
            result_artifact_id?: unknown
          }
          let status: string | null = null
          if (
            event.event_type === 'run.status_changed' &&
            typeof payload.to === 'string'
          ) {
            status = payload.to
          } else if (event.event_type === 'run.completed') {
            status = 'completed'
          } else if (event.event_type === 'run.failed') {
            status = 'failed'
          }

          if (status) {
            nextRun = {
              ...nextRun,
              status,
              error_message:
                event.event_type === 'run.failed' &&
                typeof payload.error === 'string'
                  ? payload.error
                  : nextRun.error_message,
              result_artifact_id:
                typeof payload.result_artifact_id === 'string'
                  ? payload.result_artifact_id
                  : nextRun.result_artifact_id,
            }
          }
        }
      }

      return {
        ...state,
        runs: nextRun
          ? { ...state.runs, [action.payload.runId]: nextRun }
          : state.runs,
        events: { ...state.events, [action.payload.runId]: nextEvents },
      }
    }
    case 'SET_ARTIFACTS':
      return {
        ...state,
        artifacts: {
          ...state.artifacts,
          [action.payload.runId]: action.payload.artifacts,
        },
      }
    case 'SET_APPROVALS':
      return {
        ...state,
        approvals: {
          ...state.approvals,
          [action.payload.runId]: action.payload.approvals,
        },
      }
    case 'UPDATE_APPROVAL':
      return {
        ...state,
        approvals: {
          ...state.approvals,
          [action.payload.runId]: (
            state.approvals[action.payload.runId] || []
          ).map((approval) =>
            approval.id === action.payload.approval.id
              ? action.payload.approval
              : approval,
          ),
        },
      }
    case 'SET_SSE_CONNECTED':
      return { ...state, sseConnected: action.payload }
    case 'TIMELINE':
      return {
        ...state,
        timeline: threadTimelineReducer(state.timeline, action.payload),
      }
    case 'CLEAR_ERROR':
      return { ...state, error: null }
    default:
      return state
  }
}

// ==================== Context ====================

export interface AgentContextValue {
  state: AgentState
  dispatch: React.Dispatch<AgentAction>
  loadThreads: () => Promise<void>
  createThread: (title?: string) => Promise<Thread>
  createRun: (
    threadId: string,
    workflowName: string,
    inputMessage: string,
  ) => Promise<agentApi.Run>
  loadRun: (runId: string) => Promise<agentApi.Run>
  loadThreadRuns: (threadId: string) => Promise<agentApi.Run[]>
  submitInput: (runId: string, inputText: string) => Promise<void>
  loadApprovals: (runId: string) => Promise<void>
  approveApproval: (runId: string, approvalId: string) => Promise<void>
  rejectApproval: (runId: string, approvalId: string) => Promise<void>
  answerWorkflowInput: (
    runId: string,
    inputKey: string,
    answer: string,
  ) => Promise<agentApi.InputAnswerResponse>
  decideWorkflowApproval: (
    runId: string,
    approvalId: string,
    decision: 'approve' | 'reject',
  ) => Promise<agentApi.ApprovalDecisionResponse>
  connectSSE: (runId: string, afterSequence?: number) => void
  disconnectSSE: () => void
  openThread: (threadId: string) => Promise<void>
  refreshThreadTimeline: (
    threadId: string,
  ) => Promise<agentApi.TimelineResponse>
  loadEarlierTimeline: () => Promise<void>
  sendTurn: (
    threadId: string,
    content: string,
    options?: SendTurnOptions,
  ) => Promise<agentApi.TurnCreateResponse>
  connectThreadStream: (threadId: string, afterSequence?: number) => void
  disconnectThreadStream: () => void
}

const AgentContext = createContext<AgentContextValue | undefined>(undefined)

function createClientMessageId(): string {
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.randomUUID === 'function'
  ) {
    return crypto.randomUUID()
  }
  return `client_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

const PROJECTION_REFRESH_EVENTS = new Set([
  'timeline.item.created',
  'message.completed',
  'message.failed',
  'workflow.updated',
  'workflow.completed',
  'workflow.failed',
  'workflow.step.updated',
  'workflow.artifact.created',
])

export function AgentProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(agentReducer, initialState)
  const stateRef = useRef(state)

  const runEventSourceRef = useRef<EventSource | null>(null)
  const removeRunEventListenersRef = useRef<(() => void) | null>(null)

  const threadEventSourceRef = useRef<EventSource | null>(null)
  const removeThreadEventListenersRef = useRef<(() => void) | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const timelineRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  )
  const reconnectAttemptRef = useRef(0)
  const activeThreadIdRef = useRef<string | null>(null)
  const intentionalThreadCloseRef = useRef(false)
  const connectThreadStreamRef = useRef<
    AgentContextValue['connectThreadStream'] | null
  >(null)

  useEffect(() => {
    stateRef.current = state
  }, [state])

  const loadThreads = useCallback(async () => {
    dispatch({ type: 'SET_LOADING', payload: true })
    try {
      const response = await agentApi.listThreads()
      dispatch({ type: 'SET_THREADS', payload: response.items })
    } catch (error) {
      dispatch({
        type: 'SET_ERROR',
        payload: error instanceof Error ? error.message : '加载失败',
      })
    } finally {
      dispatch({ type: 'SET_LOADING', payload: false })
    }
  }, [])

  const createThread = useCallback(
    async (title?: string): Promise<Thread> => {
      dispatch({ type: 'SET_LOADING', payload: true })
      try {
        const thread = await agentApi.createThread({ title })
        await loadThreads()
        return thread as Thread
      } finally {
        dispatch({ type: 'SET_LOADING', payload: false })
      }
    },
    [loadThreads],
  )

  const createRun = useCallback(
    async (
      threadId: string,
      workflowName: string,
      inputMessage: string,
    ): Promise<agentApi.Run> => {
      dispatch({ type: 'SET_LOADING', payload: true })
      try {
        const run = await agentApi.createRun({
          thread_id: threadId,
          workflow_name: workflowName,
          input_message: inputMessage,
        })
        dispatch({ type: 'SET_RUN', payload: run as Run })
        return run
      } finally {
        dispatch({ type: 'SET_LOADING', payload: false })
      }
    },
    [],
  )

  const loadRun = useCallback(async (runId: string): Promise<agentApi.Run> => {
    const run = await agentApi.getRun(runId)
    dispatch({ type: 'SET_RUN', payload: run as Run })
    return run
  }, [])

  const loadThreadRuns = useCallback(
    async (threadId: string): Promise<agentApi.Run[]> => {
      const response = await agentApi.listThreadRuns(threadId)
      dispatch({
        type: 'SET_THREAD_RUNS',
        payload: { threadId, runs: response.items as Run[] },
      })
      return response.items
    },
    [],
  )

  const submitInput = useCallback(
    async (runId: string, inputText: string) => {
      await agentApi.submitInput(runId, inputText)
      await loadRun(runId)
    },
    [loadRun],
  )

  const loadApprovals = useCallback(async (runId: string) => {
    try {
      const response = await agentApi.getRunApprovals(runId)
      dispatch({
        type: 'SET_APPROVALS',
        payload: { runId, approvals: response.approvals },
      })
    } catch (error) {
      dispatch({
        type: 'SET_ERROR',
        payload: error instanceof Error ? error.message : '加载审批失败',
      })
    }
  }, [])

  const approveApproval = useCallback(
    async (runId: string, approvalId: string) => {
      try {
        await agentApi.approveApproval(runId, approvalId)
        await loadApprovals(runId)
      } catch (error) {
        dispatch({
          type: 'SET_ERROR',
          payload: error instanceof Error ? error.message : '审批操作失败',
        })
      }
    },
    [loadApprovals],
  )

  const rejectApproval = useCallback(
    async (runId: string, approvalId: string) => {
      try {
        await agentApi.rejectApproval(runId, approvalId)
        await loadApprovals(runId)
      } catch (error) {
        dispatch({
          type: 'SET_ERROR',
          payload: error instanceof Error ? error.message : '审批操作失败',
        })
      }
    },
    [loadApprovals],
  )

  const connectSSE = useCallback((runId: string, afterSequence = 0) => {
    removeRunEventListenersRef.current?.()
    runEventSourceRef.current?.close()

    dispatch({ type: 'SET_SSE_CONNECTED', payload: false })
    const source = agentApi.createEventSource(runId, afterSequence)
    runEventSourceRef.current = source
    source.onopen = () => dispatch({ type: 'SET_SSE_CONNECTED', payload: true })
    removeRunEventListenersRef.current = agentApi.listenToRunEvents(
      source,
      runId,
      (event) => {
        dispatch({
          type: 'APPEND_EVENTS',
          payload: { runId, events: [event as AgentEvent] },
        })
      },
    )
    source.onerror = () => {
      dispatch({ type: 'SET_SSE_CONNECTED', payload: false })
      source.close()
    }
  }, [])

  const disconnectSSE = useCallback(() => {
    removeRunEventListenersRef.current?.()
    removeRunEventListenersRef.current = null
    runEventSourceRef.current?.close()
    runEventSourceRef.current = null
    dispatch({ type: 'SET_SSE_CONNECTED', payload: false })
  }, [])

  const refreshThreadTimeline = useCallback(async (threadId: string) => {
    const page = await agentApi.getThreadTimeline(threadId)
    if (activeThreadIdRef.current === threadId) {
      dispatch({
        type: 'TIMELINE',
        payload: { type: 'timeline/pageReceived', page },
      })
    }
    return page
  }, [])

  const scheduleTimelineRefresh = useCallback(
    (threadId: string) => {
      if (timelineRefreshTimerRef.current)
        clearTimeout(timelineRefreshTimerRef.current)
      timelineRefreshTimerRef.current = setTimeout(() => {
        timelineRefreshTimerRef.current = null
        if (activeThreadIdRef.current !== threadId) return
        void refreshThreadTimeline(threadId).catch((error) => {
          dispatch({
            type: 'SET_ERROR',
            payload: error instanceof Error ? error.message : '刷新对话失败',
          })
        })
      }, 80)
    },
    [refreshThreadTimeline],
  )

  const disconnectThreadStream = useCallback(() => {
    intentionalThreadCloseRef.current = true
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    reconnectTimerRef.current = null
    if (timelineRefreshTimerRef.current)
      clearTimeout(timelineRefreshTimerRef.current)
    timelineRefreshTimerRef.current = null
    removeThreadEventListenersRef.current?.()
    removeThreadEventListenersRef.current = null
    threadEventSourceRef.current?.close()
    threadEventSourceRef.current = null
    activeThreadIdRef.current = null
    reconnectAttemptRef.current = 0
    dispatch({
      type: 'TIMELINE',
      payload: { type: 'timeline/connectionChanged', connection: 'offline' },
    })
  }, [])

  const connectThreadStream = useCallback(
    (threadId: string, afterSequence?: number) => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      removeThreadEventListenersRef.current?.()
      threadEventSourceRef.current?.close()

      intentionalThreadCloseRef.current = false
      activeThreadIdRef.current = threadId
      const cursor = afterSequence ?? stateRef.current.timeline.latestCursor
      const connection =
        reconnectAttemptRef.current > 0 ? 'reconnecting' : 'connecting'
      dispatch({
        type: 'TIMELINE',
        payload: { type: 'timeline/connectionChanged', connection },
      })

      const source = agentApi.createThreadEventSource(threadId, cursor)
      threadEventSourceRef.current = source
      source.onopen = () => {
        reconnectAttemptRef.current = 0
        dispatch({
          type: 'TIMELINE',
          payload: {
            type: 'timeline/connectionChanged',
            connection: 'connected',
          },
        })
      }
      removeThreadEventListenersRef.current = agentApi.listenToThreadEvents(
        source,
        (event) => {
          dispatch({
            type: 'TIMELINE',
            payload: { type: 'timeline/eventReceived', threadId, event },
          })
          if (PROJECTION_REFRESH_EVENTS.has(event.event_type))
            scheduleTimelineRefresh(threadId)
        },
      )

      source.onerror = () => {
        if (
          intentionalThreadCloseRef.current ||
          activeThreadIdRef.current !== threadId
        )
          return
        removeThreadEventListenersRef.current?.()
        removeThreadEventListenersRef.current = null
        source.close()
        if (threadEventSourceRef.current === source)
          threadEventSourceRef.current = null

        reconnectAttemptRef.current += 1
        dispatch({
          type: 'TIMELINE',
          payload: {
            type: 'timeline/connectionChanged',
            connection: 'reconnecting',
          },
        })
        const delay = Math.min(
          1000 * 2 ** (reconnectAttemptRef.current - 1),
          15000,
        )
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null
          const recover = async () => {
            let recoveredCursor = stateRef.current.timeline.latestCursor
            const response = await agentApi.getThreadEvents(
              threadId,
              recoveredCursor,
              1000,
            )
            for (const event of response.events) {
              dispatch({
                type: 'TIMELINE',
                payload: { type: 'timeline/eventReceived', threadId, event },
              })
              recoveredCursor = Math.max(recoveredCursor, event.sequence)
            }
            if (response.latest_cursor > recoveredCursor) {
              await refreshThreadTimeline(threadId)
              recoveredCursor = response.latest_cursor
            }
            if (
              !intentionalThreadCloseRef.current &&
              activeThreadIdRef.current === threadId
            ) {
              connectThreadStreamRef.current?.(threadId, recoveredCursor)
            }
          }
          void recover().catch(() => {
            if (
              !intentionalThreadCloseRef.current &&
              activeThreadIdRef.current === threadId
            ) {
              connectThreadStreamRef.current?.(
                threadId,
                stateRef.current.timeline.latestCursor,
              )
            }
          })
        }, delay)
      }
    },
    [refreshThreadTimeline, scheduleTimelineRefresh],
  )

  useEffect(() => {
    connectThreadStreamRef.current = connectThreadStream
  }, [connectThreadStream])

  const openThread = useCallback(
    async (threadId: string) => {
      disconnectThreadStream()
      activeThreadIdRef.current = threadId
      intentionalThreadCloseRef.current = false
      dispatch({ type: 'SET_CURRENT_THREAD', payload: threadId })
      dispatch({
        type: 'TIMELINE',
        payload: { type: 'timeline/reset', threadId },
      })
      dispatch({ type: 'SET_LOADING', payload: true })
      try {
        const page = await agentApi.getThreadTimeline(threadId)
        if (activeThreadIdRef.current !== threadId) return
        dispatch({
          type: 'TIMELINE',
          payload: { type: 'timeline/pageReceived', page },
        })
        connectThreadStream(threadId, page.latest_cursor)
      } catch (error) {
        dispatch({
          type: 'SET_ERROR',
          payload: error instanceof Error ? error.message : '加载对话失败',
        })
        dispatch({
          type: 'TIMELINE',
          payload: {
            type: 'timeline/connectionChanged',
            connection: 'offline',
          },
        })
      } finally {
        dispatch({ type: 'SET_LOADING', payload: false })
      }
    },
    [connectThreadStream, disconnectThreadStream],
  )

  const loadEarlierTimeline = useCallback(async () => {
    const timeline = stateRef.current.timeline
    if (
      !timeline.threadId ||
      !timeline.hasMore ||
      timeline.previousCursor === null
    )
      return
    const page = await agentApi.getThreadTimeline(
      timeline.threadId,
      timeline.previousCursor,
    )
    if (activeThreadIdRef.current !== timeline.threadId) return
    dispatch({
      type: 'TIMELINE',
      payload: { type: 'timeline/pageReceived', page, prepend: true },
    })
  }, [])

  const sendTurn = useCallback(
    async (
      threadId: string,
      content: string,
      options: SendTurnOptions = {},
    ) => {
      const response = await agentApi.createTurn(threadId, {
        content,
        attachments: options.attachments ?? [],
        context_refs: options.contextRefs ?? [],
        client_message_id: options.clientMessageId ?? createClientMessageId(),
        preferred_action: options.preferredAction,
      })
      if (activeThreadIdRef.current === threadId) {
        await refreshThreadTimeline(threadId)
        if (!threadEventSourceRef.current)
          connectThreadStream(threadId, response.timeline_cursor)
      }
      return response
    },
    [connectThreadStream, refreshThreadTimeline],
  )

  const syncActiveWorkflow = useCallback(async () => {
    const threadId = activeThreadIdRef.current
    if (!threadId) return
    await refreshThreadTimeline(threadId)
    if (!threadEventSourceRef.current) {
      connectThreadStream(threadId, stateRef.current.timeline.latestCursor)
    }
  }, [connectThreadStream, refreshThreadTimeline])

  const answerWorkflowInput = useCallback(
    async (runId: string, inputKey: string, answer: string) => {
      const response = await agentApi.submitInputAnswer(runId, inputKey, answer)
      await syncActiveWorkflow()
      return response
    },
    [syncActiveWorkflow],
  )

  const decideWorkflowApproval = useCallback(
    async (
      runId: string,
      approvalId: string,
      decision: 'approve' | 'reject',
    ) => {
      const response = decision === 'approve'
        ? await agentApi.approveApproval(runId, approvalId)
        : await agentApi.rejectApproval(runId, approvalId)
      await syncActiveWorkflow()
      return response
    },
    [syncActiveWorkflow],
  )

  useEffect(() => {
    return () => {
      removeRunEventListenersRef.current?.()
      runEventSourceRef.current?.close()
      intentionalThreadCloseRef.current = true
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      if (timelineRefreshTimerRef.current)
        clearTimeout(timelineRefreshTimerRef.current)
      removeThreadEventListenersRef.current?.()
      threadEventSourceRef.current?.close()
    }
  }, [])

  const value: AgentContextValue = {
    state,
    dispatch,
    loadThreads,
    createThread,
    createRun,
    loadRun,
    loadThreadRuns,
    submitInput,
    loadApprovals,
    approveApproval,
    rejectApproval,
    answerWorkflowInput,
    decideWorkflowApproval,
    connectSSE,
    disconnectSSE,
    openThread,
    refreshThreadTimeline,
    loadEarlierTimeline,
    sendTurn,
    connectThreadStream,
    disconnectThreadStream,
  }

  return <AgentContext.Provider value={value}>{children}</AgentContext.Provider>
}

// Context 与 hook 暂时共置，页面组件拆分时再迁移到独立模块。
// eslint-disable-next-line react-refresh/only-export-components
export function useAgent(): AgentContextValue {
  const context = useContext(AgentContext)
  if (context === undefined) {
    throw new Error('useAgent must be used within an AgentProvider')
  }
  return context
}
