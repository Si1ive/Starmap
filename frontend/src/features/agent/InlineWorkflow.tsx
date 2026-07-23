import { type FormEvent, useEffect, useState } from 'react'
import {
  AlertCircle,
  Check,
  ChevronDown,
  Circle,
  FileText,
  LoaderCircle,
} from 'lucide-react'
import type {
  WorkflowArtifactView,
  WorkflowStepView,
  WorkflowView,
} from '../../api/agent'

interface InlineWorkflowProps {
  workflow: WorkflowView
  onAnswerInput: (runId: string, inputKey: string, answer: string) => Promise<void>
  onApprove: (runId: string, approvalId: string) => Promise<void>
  onReject: (runId: string, approvalId: string) => Promise<void>
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

function publicText(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() || null
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    const items = value.map(publicText).filter((item): item is string => Boolean(item))
    return items.length > 0 ? items.join('、') : null
  }
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    for (const key of ['summary', 'content', 'description', 'text', 'message']) {
      const text = publicText(record[key])
      if (text) return text
    }
  }
  return null
}

function ArtifactCard({ artifact }: { artifact: WorkflowArtifactView }) {
  const [open, setOpen] = useState(false)
  const summary = publicText(artifact.summary) || '已生成一项结果'
  const detail = publicText(artifact.content)
  const canExpand = Boolean(detail && detail !== summary)

  return (
    <article className="inline-workflow__artifact">
      <div className="inline-workflow__artifact-heading">
        <FileText aria-hidden="true" size={14} />
        <span>
          <strong>{artifact.title}</strong>
          <small>{summary}</small>
        </span>
        {canExpand ? (
          <button
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            type="button"
          >
            {open ? '收起' : '查看'}
          </button>
        ) : null}
      </div>
      {open && detail ? <p className="inline-workflow__artifact-content">{detail}</p> : null}
    </article>
  )
}

export default function InlineWorkflow({
  workflow,
  onAnswerInput,
  onApprove,
  onReject,
}: InlineWorkflowProps) {
  const initiallyOpen = !['completed', 'cancelled'].includes(workflow.status)
  const [open, setOpen] = useState(initiallyOpen)
  const [answer, setAnswer] = useState('')
  const [pendingAction, setPendingAction] = useState<'answer' | 'approve' | 'reject' | null>(null)
  const [interactionError, setInteractionError] = useState<string | null>(null)
  const statusLabel = WORKFLOW_STATUS_LABELS[workflow.status] ?? workflow.status
  const progress = workflow.progress.total > 0
    ? `${workflow.progress.completed}/${workflow.progress.total}`
    : null

  useEffect(() => {
    if (workflow.pending_input || workflow.pending_approval) setOpen(true)
  }, [workflow.pending_approval, workflow.pending_input])

  const handleAnswer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const pendingInput = workflow.pending_input
    const value = answer.trim()
    if (!pendingInput || !value || pendingAction) return
    setPendingAction('answer')
    setInteractionError(null)
    try {
      await onAnswerInput(pendingInput.run_id, pendingInput.input_key, value)
      setAnswer('')
    } catch (error) {
      setInteractionError(error instanceof Error ? error.message : '提交失败，请稍后重试')
    } finally {
      setPendingAction(null)
    }
  }

  const handleDecision = async (decision: 'approve' | 'reject') => {
    const approval = workflow.pending_approval
    if (!approval || pendingAction) return
    setPendingAction(decision)
    setInteractionError(null)
    try {
      if (decision === 'approve') await onApprove(approval.run_id, approval.id)
      else await onReject(approval.run_id, approval.id)
    } catch (error) {
      setInteractionError(error instanceof Error ? error.message : '操作失败，请稍后重试')
    } finally {
      setPendingAction(null)
    }
  }

  const approvalSummary = workflow.pending_approval
    ? publicText(workflow.pending_approval.change) || '该操作会继续执行当前工作流。'
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
            <form className="inline-workflow__interaction" onSubmit={(event) => void handleAnswer(event)}>
              <label htmlFor={`workflow-input-${workflow.pending_input.id}`}>
                {workflow.pending_input.question}
              </label>
              <textarea
                disabled={pendingAction !== null}
                id={`workflow-input-${workflow.pending_input.id}`}
                onChange={(event) => setAnswer(event.target.value)}
                placeholder="在这里补充信息"
                rows={2}
                value={answer}
              />
              <div className="inline-workflow__actions">
                <button disabled={!answer.trim() || pendingAction !== null} type="submit">
                  {pendingAction === 'answer' ? (
                    <><LoaderCircle className="agent-chat-spin" size={13} />提交中</>
                  ) : '提交并继续'}
                </button>
              </div>
            </form>
          ) : null}

          {workflow.pending_approval ? (
            <div className="inline-workflow__interaction">
              <strong>确认后继续执行</strong>
              <p>{approvalSummary}</p>
              <div className="inline-workflow__actions">
                <button
                  className="is-secondary"
                  disabled={pendingAction !== null}
                  onClick={() => void handleDecision('reject')}
                  type="button"
                >
                  {pendingAction === 'reject' ? '拒绝中…' : '拒绝'}
                </button>
                <button
                  disabled={pendingAction !== null}
                  onClick={() => void handleDecision('approve')}
                  type="button"
                >
                  {pendingAction === 'approve' ? (
                    <><LoaderCircle className="agent-chat-spin" size={13} />确认中</>
                  ) : '确认执行'}
                </button>
              </div>
            </div>
          ) : null}

          {interactionError ? (
            <p className="inline-workflow__interaction-error" role="alert">
              <AlertCircle size={13} />
              {interactionError}
            </p>
          ) : null}

          {workflow.artifacts.length > 0 ? (
            <div className="inline-workflow__artifacts">
              {workflow.artifacts.map((artifact) => (
                <ArtifactCard artifact={artifact} key={artifact.id} />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
