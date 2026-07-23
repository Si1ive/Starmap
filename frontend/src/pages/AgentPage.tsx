import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, CheckCircle2, LoaderCircle, WifiOff } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import ChatComposer from '../features/agent/ChatComposer'
import ConversationStream from '../features/agent/ConversationStream'
import { selectTimelineItems } from '../features/agent/timeline-state'
import { useAgent } from '../store/agent-context'
import '../features/agent/agent-chat.css'

const CONNECTION_LABELS = {
  idle: '尚未连接',
  connecting: '正在连接',
  connected: '已同步',
  reconnecting: '正在恢复连接',
  offline: '连接已断开',
} as const

export default function AgentPage() {
  const { threadId } = useParams<{ threadId: string }>()
  const navigate = useNavigate()
  const {
    state,
    dispatch,
    createThread,
    answerWorkflowInput,
    decideWorkflowApproval,
    connectThreadStream,
    disconnectThreadStream,
    loadEarlierTimeline,
    loadThreads,
    openThread,
    sendTurn,
  } = useAgent()
  const [message, setMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isLoadingEarlier, setIsLoadingEarlier] = useState(false)
  const [composerFocusKey, setComposerFocusKey] = useState(0)

  const timelineItems = useMemo(
    () => selectTimelineItems(state.timeline),
    [state.timeline],
  )
  const currentThread = state.threads.find((thread) => thread.id === threadId)
  const title = state.timeline.thread?.title || currentThread?.title || '新对话'
  const isEmpty = !threadId

  useEffect(() => {
    void loadThreads()
  }, [loadThreads])

  useEffect(() => {
    if (!threadId) {
      disconnectThreadStream()
      dispatch({ type: 'SET_CURRENT_THREAD', payload: null })
      dispatch({ type: 'TIMELINE', payload: { type: 'timeline/reset', threadId: null } })
      return
    }

    void openThread(threadId)
    return () => disconnectThreadStream()
  }, [disconnectThreadStream, dispatch, openThread, threadId])

  useEffect(() => {
    if (!state.error) return
    const timer = window.setTimeout(() => dispatch({ type: 'CLEAR_ERROR' }), 5000)
    return () => window.clearTimeout(timer)
  }, [dispatch, state.error])

  const handleSend = useCallback(async () => {
    const content = message.trim()
    if (!content || isSubmitting) return
    setIsSubmitting(true)

    try {
      let targetThreadId = threadId
      if (!targetThreadId) {
        const thread = await createThread(content.slice(0, 30))
        targetThreadId = thread.id
        await openThread(thread.id)
        navigate(`/agent/${thread.id}`)
      }

      await sendTurn(targetThreadId, content)
      setMessage('')
      void loadThreads()
    } catch (error) {
      dispatch({
        type: 'SET_ERROR',
        payload: error instanceof Error ? error.message : '消息发送失败，请稍后重试',
      })
    } finally {
      setIsSubmitting(false)
    }
  }, [
    createThread,
    dispatch,
    isSubmitting,
    loadThreads,
    message,
    navigate,
    openThread,
    sendTurn,
    threadId,
  ])

  const handleLoadEarlier = useCallback(async () => {
    if (isLoadingEarlier) return
    setIsLoadingEarlier(true)
    try {
      await loadEarlierTimeline()
    } catch (error) {
      dispatch({
        type: 'SET_ERROR',
        payload: error instanceof Error ? error.message : '加载历史消息失败',
      })
    } finally {
      setIsLoadingEarlier(false)
    }
  }, [dispatch, isLoadingEarlier, loadEarlierTimeline])

  const connection = state.timeline.connection
  const ConnectionIcon = connection === 'connected'
    ? CheckCircle2
    : connection === 'offline'
      ? WifiOff
      : LoaderCircle

  const handleReconnect = useCallback(() => {
    if (!threadId) return
    disconnectThreadStream()
    connectThreadStream(threadId, state.timeline.latestCursor)
  }, [connectThreadStream, disconnectThreadStream, state.timeline.latestCursor, threadId])

  return (
    <div className={`agent-chat-page ${isEmpty ? 'agent-chat-page--empty' : ''}`}>
      {state.error ? (
        <div className="agent-chat-error" role="alert">
          <AlertCircle size={16} />
          <span>{state.error}</span>
          <button onClick={() => dispatch({ type: 'CLEAR_ERROR' })} type="button">关闭</button>
        </div>
      ) : null}

      <header className="agent-chat-header">
        <div>
          <h1>{title}</h1>
          {!isEmpty ? (
            connection === 'offline' ? (
              <button
                className={`agent-chat-connection is-${connection}`}
                onClick={handleReconnect}
                type="button"
              >
                <ConnectionIcon size={12} />
                连接已断开 · 重新连接
              </button>
            ) : (
              <span className={`agent-chat-connection is-${connection}`}>
                <ConnectionIcon
                  className={connection === 'connecting' || connection === 'reconnecting'
                    ? 'agent-chat-spin'
                    : ''}
                  size={12}
                />
                {CONNECTION_LABELS[connection]}
              </span>
            )
          ) : null}
        </div>
      </header>

      {isEmpty ? (
        <div className="agent-chat-empty">
          <div className="agent-chat-empty__intro">
            <span>Agent</span>
            <h2>今天想一起解决什么？</h2>
            <p>直接描述你的问题。需要执行预设流程时，过程会自然出现在对话中。</p>
          </div>
          <div className="agent-chat-composer-wrap">
            <ChatComposer
              autofocus
              disabled={isSubmitting}
              onChange={setMessage}
              onSubmit={() => void handleSend()}
              value={message}
            />
            <p className="agent-chat-disclaimer">Agent 可能会出错，重要信息请自行核实。</p>
          </div>
        </div>
      ) : (
        <div className="agent-chat-conversation">
          {state.loading && timelineItems.length === 0 ? (
            <div className="agent-chat-loading" role="status">
              <LoaderCircle className="agent-chat-spin" size={18} />
              正在加载对话…
            </div>
          ) : (
            <ConversationStream
              hasMore={state.timeline.hasMore}
              items={timelineItems}
              latestCursor={state.timeline.latestCursor}
              loading={isLoadingEarlier}
              onAnswerInput={async (runId, inputKey, answer) => {
                await answerWorkflowInput(runId, inputKey, answer)
              }}
              onApprove={async (runId, approvalId) => {
                await decideWorkflowApproval(runId, approvalId, 'approve')
              }}
              onContinueAfterFailure={() => setComposerFocusKey((value) => value + 1)}
              onLoadEarlier={() => void handleLoadEarlier()}
              onReject={async (runId, approvalId) => {
                await decideWorkflowApproval(runId, approvalId, 'reject')
              }}
            />
          )}
          <div className="agent-chat-composer-dock">
            <div className="agent-chat-composer-wrap">
              <ChatComposer
                disabled={isSubmitting}
                focusRequestKey={composerFocusKey}
                onChange={setMessage}
                onSubmit={() => void handleSend()}
                value={message}
              />
              <p className="agent-chat-disclaimer">Agent 可能会出错，重要信息请自行核实。</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
