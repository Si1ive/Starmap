import { useEffect, useRef } from 'react'
import type { TimelineItem } from '../../api/agent'
import InlineWorkflow from './InlineWorkflow'

interface ConversationStreamProps {
  items: TimelineItem[]
  hasMore: boolean
  loading: boolean
  latestCursor: number
  onLoadEarlier: () => void
  onAnswerInput: (runId: string, inputKey: string, answer: string) => Promise<void>
  onApprove: (runId: string, approvalId: string) => Promise<void>
  onReject: (runId: string, approvalId: string) => Promise<void>
  onContinueAfterFailure: () => void
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

    return (
      <div className="agent-message agent-message--assistant">
        <div className="agent-message__content">
          {item.message.content || (item.message.status === 'streaming' ? '正在回复…' : '')}
          {item.message.status === 'streaming' ? <span className="agent-message__cursor" /> : null}
        </div>
        {item.message.status === 'failed' ? (
          <small className="agent-message__error">这条回复生成失败，请稍后重试。</small>
        ) : null}
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
  latestCursor,
  onLoadEarlier,
  onAnswerInput,
  onApprove,
  onReject,
  onContinueAfterFailure,
}: ConversationStreamProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const shouldStickToBottomRef = useRef(true)

  useEffect(() => {
    if (!shouldStickToBottomRef.current) return
    const viewport = viewportRef.current
    if (viewport) viewport.scrollTop = viewport.scrollHeight
  }, [items.length, latestCursor])

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
      </div>
    </div>
  )
}
