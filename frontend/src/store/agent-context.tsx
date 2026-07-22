/**
 * Agent 状态管理
 *
 * 使用 React Context + useReducer 管理 Agent 对话状态。
 * 支持：线程列表、当前线程、运行状态、事件流、SSE连接。
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
  error_message: string | null
  model_call_count: number
  created_at: string
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
  loading: boolean
  error: string | null
  sseConnected: boolean
}

type AgentAction =
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
  | { type: 'SET_SSE_CONNECTED'; payload: boolean }
  | { type: 'CLEAR_ERROR' }

// ==================== Reducer ====================

const initialState: AgentState = {
  threads: [],
  currentThreadId: null,
  currentRunId: null,
  runs: {},
  events: {},
  artifacts: {},
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
      return { ...state, runs: { ...state.runs, [action.payload.id]: action.payload } }
    case 'SET_RUNS':
      return { ...state, runs: { ...state.runs, ...action.payload } }
    case 'SET_THREAD_RUNS':
      return {
        ...state,
        runs: {
          ...state.runs,
          ...action.payload.runs.reduce((acc, run) => ({ ...acc, [run.id]: run }), {} as Record<string, Run>),
        },
      }
    case 'APPEND_EVENTS':
      return {
        ...state,
        events: {
          ...state.events,
          [action.payload.runId]: [
            ...(state.events[action.payload.runId] || []),
            ...action.payload.events,
          ].sort((a, b) => a.sequence - b.sequence),
        },
      }
    case 'SET_ARTIFACTS':
      return {
        ...state,
        artifacts: {
          ...state.artifacts,
          [action.payload.runId]: action.payload.artifacts,
        },
      }
    case 'SET_SSE_CONNECTED':
      return { ...state, sseConnected: action.payload }
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
  // Actions
  loadThreads: () => Promise<void>
  createThread: (title?: string) => Promise<Thread>
  createRun: (threadId: string, workflowName: string, inputMessage: string) => Promise<agentApi.Run>
  loadRun: (runId: string) => Promise<agentApi.Run>
  loadThreadRuns: (threadId: string) => Promise<agentApi.Run[]>
  submitInput: (runId: string, inputText: string) => Promise<void>
  connectSSE: (runId: string, afterSequence?: number) => void
  disconnectSSE: () => void
}

const AgentContext = createContext<AgentContextValue | undefined>(undefined)

export function AgentProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(agentReducer, initialState)
  const esRef = useRef<EventSource | null>(null)

  // Load threads
  const loadThreads = useCallback(async () => {
    dispatch({ type: 'SET_LOADING', payload: true })
    try {
      const response = await agentApi.listThreads()
      dispatch({ type: 'SET_THREADS', payload: response.items })
    } catch (e) {
      dispatch({ type: 'SET_ERROR', payload: e instanceof Error ? e.message : '加载失败' })
    } finally {
      dispatch({ type: 'SET_LOADING', payload: false })
    }
  }, [])

  // Create thread
  const createThread = useCallback(async (title?: string): Promise<Thread> => {
    dispatch({ type: 'SET_LOADING', payload: true })
    try {
      const thread = await agentApi.createThread({ title })
      await loadThreads()
      return thread as Thread
    } finally {
      dispatch({ type: 'SET_LOADING', payload: false })
    }
  }, [loadThreads])

  // Create run
  const createRun = useCallback(async (threadId: string, workflowName: string, inputMessage: string): Promise<agentApi.Run> => {
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
  }, [])

  // Load run
  const loadRun = useCallback(async (runId: string): Promise<agentApi.Run> => {
    const run = await agentApi.getRun(runId)
    dispatch({ type: 'SET_RUN', payload: run as Run })
    return run
  }, [])

  // Load thread runs
  const loadThreadRuns = useCallback(async (threadId: string): Promise<agentApi.Run[]> => {
    const response = await agentApi.listThreadRuns(threadId)
    const runs = response.items
    dispatch({
      type: 'SET_THREAD_RUNS',
      payload: { threadId, runs: runs as Run[] },
    })
    return runs
  }, [])

  // Submit input
  const submitInput = useCallback(async (runId: string, inputText: string) => {
    await agentApi.submitInput(runId, inputText)
    // Refresh run status
    await loadRun(runId)
  }, [loadRun])

  // SSE
  const connectSSE = useCallback((runId: string, afterSequence = 0) => {
    if (esRef.current) {
      esRef.current.close()
    }

    dispatch({ type: 'SET_SSE_CONNECTED', payload: false })
    const es = agentApi.createEventSource(runId, afterSequence)
    esRef.current = es

    es.onopen = () => {
      dispatch({ type: 'SET_SSE_CONNECTED', payload: true })
    }

    es.onmessage = (event) => {
      if (!event.data) return
      try {
        const data = JSON.parse(event.data)
        if (data.sequence && data.event_type) {
          dispatch({
            type: 'APPEND_EVENTS',
            payload: { runId, events: [data as AgentEvent] },
          })
        }
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      dispatch({ type: 'SET_SSE_CONNECTED', payload: false })
      es.close()
    }
  }, [])

  const disconnectSSE = useCallback(() => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    dispatch({ type: 'SET_SSE_CONNECTED', payload: false })
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (esRef.current) {
        esRef.current.close()
      }
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
    connectSSE,
    disconnectSSE,
  }

  return <AgentContext.Provider value={value}>{children}</AgentContext.Provider>
}

export function useAgent(): AgentContextValue {
  const context = useContext(AgentContext)
  if (context === undefined) {
    throw new Error('useAgent must be used within an AgentProvider')
  }
  return context
}
