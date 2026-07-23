import type {
  MessageView,
  ThreadEvent,
  TimelineItem,
  TimelineResponse,
  TimelineThreadView,
  WorkflowView,
} from '../../api/agent'

export type ThreadConnectionState =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'offline'

export interface ThreadTimelineState {
  threadId: string | null
  thread: TimelineThreadView | null
  itemIds: string[]
  itemsById: Record<string, TimelineItem>
  messagesById: Record<string, MessageView>
  workflowsByRootRunId: Record<string, WorkflowView>
  latestCursor: number
  previousCursor: number | null
  hasMore: boolean
  connection: ThreadConnectionState
}

export type ThreadTimelineAction =
  | { type: 'timeline/reset'; threadId: string | null }
  | { type: 'timeline/pageReceived'; page: TimelineResponse; prepend?: boolean }
  | {
      type: 'timeline/snapshotReceived'
      threadId: string
      latestSequence: number
      items: TimelineItem[]
      hasMore: boolean
    }
  | { type: 'timeline/eventReceived'; threadId: string; event: ThreadEvent }
  | { type: 'timeline/connectionChanged'; connection: ThreadConnectionState }

export const initialThreadTimelineState: ThreadTimelineState = {
  threadId: null,
  thread: null,
  itemIds: [],
  itemsById: {},
  messagesById: {},
  workflowsByRootRunId: {},
  latestCursor: 0,
  previousCursor: null,
  hasMore: false,
  connection: 'idle',
}

function mergeItems(
  state: ThreadTimelineState,
  items: TimelineItem[],
): Pick<
  ThreadTimelineState,
  'itemIds' | 'itemsById' | 'messagesById' | 'workflowsByRootRunId'
> {
  const itemsById = { ...state.itemsById }
  const messagesById = { ...state.messagesById }
  const workflowsByRootRunId = { ...state.workflowsByRootRunId }

  for (const item of items) {
    itemsById[item.id] = item
    if (item.message) messagesById[item.message.id] = item.message
    if (item.workflow)
      workflowsByRootRunId[item.workflow.root_run_id] = item.workflow
  }

  const itemIds = Object.values(itemsById)
    .sort((left, right) => left.sequence - right.sequence)
    .map((item) => item.id)

  return { itemIds, itemsById, messagesById, workflowsByRootRunId }
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function applyMessageEvent(
  state: ThreadTimelineState,
  event: ThreadEvent,
): ThreadTimelineState['messagesById'] {
  const messageId = stringValue(event.payload.message_id)
  if (!messageId) return state.messagesById

  const now = event.created_at
  const current = state.messagesById[messageId]
  const base: MessageView = current ?? {
    id: messageId,
    role: 'assistant',
    status: 'streaming',
    content: '',
    content_blocks: [],
    error_code: null,
    created_at: now,
    updated_at: now,
    completed_at: null,
  }

  if (event.event_type === 'message.delta') {
    const delta = stringValue(event.payload.delta) ?? ''
    return {
      ...state.messagesById,
      [messageId]: {
        ...base,
        status: 'streaming',
        content: `${base.content ?? ''}${delta}`,
        updated_at: now,
      },
    }
  }

  if (event.event_type === 'message.completed') {
    const message = event.payload.message
    const publicMessage =
      message && typeof message === 'object'
        ? (message as Record<string, unknown>)
        : {}
    return {
      ...state.messagesById,
      [messageId]: {
        ...base,
        role:
          publicMessage.role === 'system' || publicMessage.role === 'user'
            ? publicMessage.role
            : 'assistant',
        status: 'completed',
        content: stringValue(publicMessage.content) ?? base.content,
        updated_at: now,
        completed_at: now,
      },
    }
  }

  if (event.event_type === 'message.failed') {
    return {
      ...state.messagesById,
      [messageId]: {
        ...base,
        status: 'failed',
        error_code: stringValue(event.payload.error_code),
        updated_at: now,
      },
    }
  }

  return state.messagesById
}

function applyWorkflowEvent(
  state: ThreadTimelineState,
  event: ThreadEvent,
): ThreadTimelineState['workflowsByRootRunId'] {
  const rootRunId = stringValue(event.payload.root_run_id)
  if (!rootRunId) return state.workflowsByRootRunId
  const current = state.workflowsByRootRunId[rootRunId]
  if (!current) return state.workflowsByRootRunId

  let status = stringValue(event.payload.status) ?? current.status
  if (event.event_type === 'workflow.completed') status = 'completed'
  if (event.event_type === 'workflow.failed') status = 'failed'
  if (event.event_type === 'workflow.cancelled') status = 'cancelled'

  const currentStep =
    event.event_type === 'workflow.step.updated'
      ? (stringValue(event.payload.label) ?? current.current_step)
      : current.current_step

  return {
    ...state.workflowsByRootRunId,
    [rootRunId]: {
      ...current,
      status,
      current_step: currentStep,
      updated_at: event.created_at,
    },
  }
}

export function threadTimelineReducer(
  state: ThreadTimelineState,
  action: ThreadTimelineAction,
): ThreadTimelineState {
  switch (action.type) {
    case 'timeline/reset':
      return {
        ...initialThreadTimelineState,
        threadId: action.threadId,
      }
    case 'timeline/pageReceived': {
      if (state.threadId && state.threadId !== action.page.thread.id)
        return state
      const merged = mergeItems(state, action.page.items)
      return {
        ...state,
        ...merged,
        threadId: action.page.thread.id,
        thread: action.page.thread,
        latestCursor: Math.max(state.latestCursor, action.page.latest_cursor),
        previousCursor: action.page.previous_cursor,
        hasMore: action.page.has_more,
      }
    }
    case 'timeline/snapshotReceived': {
      if (state.threadId && state.threadId !== action.threadId) return state
      const merged = mergeItems(state, action.items)
      return {
        ...state,
        ...merged,
        threadId: action.threadId,
        latestCursor: Math.max(state.latestCursor, action.latestSequence),
        hasMore: action.hasMore || state.hasMore,
      }
    }
    case 'timeline/eventReceived': {
      if (state.threadId !== action.threadId) return state

      if (action.event.event_type === 'timeline.snapshot') {
        const items = Array.isArray(action.event.payload.items)
          ? (action.event.payload.items as TimelineItem[])
          : []
        const latestSequence =
          typeof action.event.payload.latest_sequence === 'number'
            ? action.event.payload.latest_sequence
            : action.event.sequence
        return threadTimelineReducer(state, {
          type: 'timeline/snapshotReceived',
          threadId: action.threadId,
          latestSequence,
          items,
          hasMore: action.event.payload.has_more === true,
        })
      }

      if (action.event.sequence <= state.latestCursor) return state

      const messagesById = action.event.event_type.startsWith('message.')
        ? applyMessageEvent(state, action.event)
        : state.messagesById
      const workflowsByRootRunId = action.event.event_type.startsWith(
        'workflow.',
      )
        ? applyWorkflowEvent(state, action.event)
        : state.workflowsByRootRunId

      return {
        ...state,
        messagesById,
        workflowsByRootRunId,
        latestCursor: action.event.sequence,
      }
    }
    case 'timeline/connectionChanged':
      return { ...state, connection: action.connection }
    default:
      return state
  }
}

export function selectTimelineItems(
  state: ThreadTimelineState,
): TimelineItem[] {
  return state.itemIds
    .map((itemId) => state.itemsById[itemId])
    .filter((item): item is TimelineItem => Boolean(item))
    .map((item) => ({
      ...item,
      message: item.message
        ? (state.messagesById[item.message.id] ?? item.message)
        : null,
      workflow: item.workflow
        ? (state.workflowsByRootRunId[item.workflow.root_run_id] ??
          item.workflow)
        : null,
    }))
}
