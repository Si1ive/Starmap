import { useEffect, useRef } from 'react'
import type { TimelineItem } from '../../api/agent'
import InlineWorkflow from './InlineWorkflow'
import MarkdownContent from './MarkdownContent'

interface ConversationStreamProps {
  items: TimelineItem[]
  hasMore: boolean
  loading: boolean
  awaitingResponse: boolean
  latestCursor: number
  onLoadEarlier: () => void
  onAnswerInput: (runId: string, inputKey: string, answer: string) => Promise<void>
  onApprove: (runId: string, approvalId: string) => Promise<void>
  onReject: (runId: string, approvalId: string) => Promise<void>
  onContinueAfterFailure: () => void
}

function AssistantPending() {
  return (
    <span className="agent-message__pending" role="status">
      <span className="agent-message__pending-dots" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span>正在组织回答</span>
    </span>
  )
}

function TimelineItemView({
  item,
  onAnswerInput,
  onApprove,
  onReject,
  onContinueAfterFailure,
}: Pick<
  ConversationStreamProps,
  'onAnswerInput' | 'onApprove' | 'onReject' | 'onContinueAfterFailure'
> & {
  item: TimelineItem
}) {
  if (item.type === 'message' && item.message) {
    if (item.message.role === 'user') {
      return (
        <div className="agent-message agent-message--user">
          <div className="agent-message__bubble">{item.message.content}</div>
        </div>
      )
    }

    const isStreaming = item.message.status === 'streaming'
    const hasContent = Boolean(item.message.content)
    const fallbackError = '这条回复生成失败，请稍后重试。'
    const errorMessage = item.message.error_message || fallbackError
    const legacyFailureContent =
      item.message.content === errorMessage || item.message.content === fallbackError
    const retainedContent = legacyFailureContent ? null : item.message.content

    return (
      <div className="agent-message agent-message--assistant">
        {item.message.status === 'failed' ? (
          <>
            {retainedContent ? (
              <div className="agent-message__content">
                <MarkdownContent content={retainedContent} />
              </div>
            ) : null}
            <small className="agent-message__error">{errorMessage}</small>
          </>
        ) : (
          <div className="agent-message__content">
            {isStreaming && !hasContent ? (
              <AssistantPending />
            ) : (
              <>
                <MarkdownContent content={item.message.content} />
                {isStreaming ? <span className="agent-message__cursor" /> : null}
              </>
            )}
          </div>
        )}
      </div>
    )
  }

  if (item.type === 'workflow' && item.workflow) {
    return (
      <InlineWorkflow
        onAnswerInput={onAnswerInput}
        onApprove={onApprove}
        onContinueAfterFailure={onContinueAfterFailure}
        onReject={onReject}
        workflow={item.workflow}
      />
    )
  }

  if (item.type === 'notice' && item.notice) {
    const text = typeof item.notice.text === 'string' ? item.notice.text : '对话状态已更新'
    return <div className="agent-chat-notice">{text}</div>
  }

  return null
}

export default function ConversationStream({
  items,
  hasMore,
  loading,
  awaitingResponse,
  latestCursor,
  onLoadEarlier,
  onAnswerInput,
  onApprove,
  onReject,
  onContinueAfterFailure,
}: ConversationStreamProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const shouldStickToBottomRef = useRef(true)
  const hasStreamingAssistant = items.some(
    (item) => item.message?.role === 'assistant' && item.message.status === 'streaming',
  )

  useEffect(() => {
    if (!shouldStickToBottomRef.current) return
    const viewport = viewportRef.current
    if (viewport) viewport.scrollTop = viewport.scrollHeight
  }, [awaitingResponse, items.length, latestCursor])

  return (
    <div
      className="agent-chat-stream"
      onScroll={(event) => {
        const viewport = event.currentTarget
        shouldStickToBottomRef.current =
          viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 120
      }}
      ref={viewportRef}
    >
      <div className="agent-chat-stream__inner">
        {hasMore ? (
          <button
            className="agent-chat-history-button"
            disabled={loading}
            onClick={onLoadEarlier}
            type="button"
          >
            {loading ? '正在加载…' : '加载更早的对话'}
          </button>
        ) : null}
        {items.map((item) => (
          <TimelineItemView
            item={item}
            key={item.id}
            onAnswerInput={onAnswerInput}
            onApprove={onApprove}
            onContinueAfterFailure={onContinueAfterFailure}
            onReject={onReject}
          />
        ))}
        {awaitingResponse && !hasStreamingAssistant ? (
          <div className="agent-message agent-message--assistant">
            <div className="agent-message__content">
              <AssistantPending />
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
