import { useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  Check,
  ChevronDown,
  Circle,
  LoaderCircle,
} from 'lucide-react'
import type { TimelineItem, WorkflowStepView, WorkflowView } from '../../api/agent'

interface ConversationStreamProps {
  items: TimelineItem[]
  hasMore: boolean
  loading: boolean
  latestCursor: number
  onLoadEarlier: () => void
}

const WORKFLOW_STATUS_LABELS: Record<string, string> = {
  queued: '准备中',
  running: '执行中',
  waiting_for_user: '等待你的补充',
  waiting_for_approval: '等待你的确认',
  completed: '已完成',
  failed: '执行失败',
  cancelled: '已停止',
  expired: '已过期',
}

function stepIcon(step: WorkflowStepView) {
  if (step.status === 'completed' || step.status === 'skipped') return <Check size={13} />
  if (step.status === 'running' || step.status === 'started') {
    return <LoaderCircle className="agent-chat-spin" size={13} />
  }
  if (step.status === 'failed') return <AlertCircle size={13} />
  return <Circle size={9} />
}

function InlineWorkflow({ workflow }: { workflow: WorkflowView }) {
  const initiallyOpen = !['completed', 'cancelled'].includes(workflow.status)
  const [open, setOpen] = useState(initiallyOpen)
  const statusLabel = WORKFLOW_STATUS_LABELS[workflow.status] ?? workflow.status
  const progress = workflow.progress.total > 0
    ? `${workflow.progress.completed}/${workflow.progress.total}`
    : null

  return (
    <section className={`inline-workflow inline-workflow--${workflow.status}`}>
      <span aria-hidden="true" className="inline-workflow__rail" />
      <button
        aria-expanded={open}
        className="inline-workflow__summary"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span className="inline-workflow__heading">
          <strong>{workflow.title}</strong>
          <small>{workflow.current_step || workflow.summary || statusLabel}</small>
        </span>
        <span className="inline-workflow__meta">
          {progress ? <span>{progress}</span> : null}
          <span>{statusLabel}</span>
          <ChevronDown className={open ? 'is-open' : ''} size={15} />
        </span>
      </button>

      {open ? (
        <div className="inline-workflow__details">
          {workflow.steps.length > 0 ? (
            <ol className="inline-workflow__steps">
              {workflow.steps.map((step) => (
                <li className={`is-${step.status}`} key={step.id}>
                  <span>{stepIcon(step)}</span>
                  <span>{step.label}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p>{workflow.summary || '正在安排执行步骤…'}</p>
          )}
          {workflow.pending_input ? (
            <div className="inline-workflow__attention">需要你补充信息后才能继续</div>
          ) : null}
          {workflow.pending_approval ? (
            <div className="inline-workflow__attention">有一项操作等待你的确认</div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

function TimelineItemView({ item }: { item: TimelineItem }) {
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
    return <InlineWorkflow workflow={item.workflow} />
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
        {items.map((item) => <TimelineItemView item={item} key={item.id} />)}
      </div>
    </div>
  )
}
