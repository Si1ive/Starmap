import { type FormEvent, useEffect, useState } from 'react'
import {
  AlertCircle,
  Check,
  ChevronDown,
  Circle,
  Database,
  FileText,
  LoaderCircle,
  Play,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type {
  WorkflowArtifactView,
  WorkflowActivityView,
  WorkflowStepView,
  WorkflowView,
} from '../../api/agent'
import MarkdownContent from './MarkdownContent'

interface InlineWorkflowProps {
  workflow: WorkflowView
  onAnswerInput: (runId: string, inputKey: string, answer: string) => Promise<void>
  onApprove: (runId: string, approvalId: string) => Promise<void>
  onReject: (runId: string, approvalId: string) => Promise<void>
  onContinueAfterFailure: () => void
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
    for (const key of [
      'summary',
      'content',
      'description',
      'text',
      'message',
      'name',
      'title',
      'filename',
      'source_label',
      'outline_code',
    ]) {
      const text = publicText(record[key])
      if (text) return text
    }
  }
  return null
}

type PublicRecord = Record<string, unknown>

const HIT_GROUPS = [
  { type: 'knowledge_point', label: '命中知识点' },
  { type: 'question', label: '命中题目' },
  { type: 'other', label: '其他命中' },
] as const

const SEGMENT_LABELS: Record<string, string> = {
  summary: '知识点摘要',
  content: '正文',
  title: '标题',
  explanation: '解析',
  option: '选项',
}

function asRecord(value: unknown): PublicRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as PublicRecord
    : null
}

function asRecords(value: unknown): PublicRecord[] {
  return Array.isArray(value)
    ? value.filter((item): item is PublicRecord => Boolean(asRecord(item)))
    : []
}

function segmentLabel(segmentType: string | null, entityType: string): string {
  if (entityType === 'question' && segmentType === 'content') return '题面'
  if (entityType === 'knowledge_point' && segmentType === 'content') return '知识点正文'
  return (segmentType && SEGMENT_LABELS[segmentType]) || '命中片段'
}

function chapterSummary(document: PublicRecord): string | null {
  const chapters = asRecords(document.chapters)
  const names = chapters
    .map((chapter) => publicText(chapter.name) || publicText(chapter.title))
    .filter((name): name is string => Boolean(name))
  if (names.length > 0) return `章节：${names.slice(0, 2).join(' / ')}`

  const chapterIds = Array.isArray(document.chapter_ids)
    ? document.chapter_ids.map(publicText).filter((id): id is string => Boolean(id))
    : []
  return chapterIds.length > 0 ? '章节信息待同步' : null
}

function sourceSummary(document: PublicRecord): string | null {
  const source = asRecord(document.source)
  if (!source) return null
  const sourceName = publicText(source.filename) || publicText(source.title) || publicText(source.source_label)
  const page = publicText(source.page_no)
  if (!sourceName && !page) return null
  return [sourceName, page ? `第 ${page} 页` : null].filter(Boolean).join(' · ')
}

function HitSummary({ document, index }: { document: PublicRecord; index: number }) {
  const entityType = publicText(document.entity_type) || 'other'
  const title = publicText(document.title) || publicText(document.entity_title) || `未命名命中 ${index + 1}`
  const details = [
    chapterSummary(document),
    segmentLabel(publicText(document.segment_type), entityType),
    sourceSummary(document),
  ].filter((item): item is string => Boolean(item))

  return (
    <li className={`inline-workflow__source-hit is-${entityType}`}>
      <span className="inline-workflow__source-hit-mark" aria-hidden="true" />
      <span className="inline-workflow__source-hit-body">
        <strong>{title}</strong>
        <small>{details.join(' · ')}</small>
      </span>
    </li>
  )
}

const ARTIFACT_TYPE_LABELS: Record<string, string> = {
  explanation: '讲解',
  practice: '题目练习',
  feedback: '批改结果',
  plan: '学习计划',
  message: '回答',
}

function artifactTypeLabel(type: string): string {
  return ARTIFACT_TYPE_LABELS[type] || '执行结果'
}

function artifactMarkdown(content: unknown): string | null {
  if (typeof content === 'string') return content.trim() || null
  const record = asRecord(content)
  if (!record) return null
  for (const key of ['content', 'body', 'markdown', 'text']) {
    if (typeof record[key] === 'string' && record[key].trim()) return record[key].trim()
  }
  return null
}

function ArtifactCard({ artifact }: { artifact: WorkflowArtifactView }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(artifact.type === 'explanation')
  const typeLabel = artifactTypeLabel(artifact.type)
  const summary = publicText(artifact.summary) || '已生成一项结果'
  const detail = artifactMarkdown(artifact.content)
  const canExpand = Boolean(detail && detail !== summary)
  const practiceAction = artifact.actions.find((action) => (
    action.type === 'open_practice' && typeof action.target_id === 'string'
  ))

  return (
    <article className={`inline-workflow__artifact is-${artifact.type}`}>
      <div className="inline-workflow__artifact-heading">
        <FileText aria-hidden="true" size={14} />
        <span>
          <small className="inline-workflow__artifact-type">{typeLabel}</small>
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
      {open && detail ? <MarkdownContent className="inline-workflow__artifact-content" content={detail} /> : null}
      {practiceAction ? (
        <button
          className="inline-workflow__artifact-action"
          onClick={() => navigate(`/practice/${encodeURIComponent(String(practiceAction.target_id))}`)}
          type="button"
        >
          <Play aria-hidden="true" size={13} />
          {typeof practiceAction.label === 'string' ? practiceAction.label : '开始练习'}
        </button>
      ) : null}
    </article>
  )
}

function ActivityCard({ activity }: { activity: WorkflowActivityView }) {
  const documents = Array.isArray(activity.metadata.documents)
    ? activity.metadata.documents.filter(
      (item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'),
    )
    : []
  const query = publicText(activity.metadata.query)
  const total = publicText(activity.metadata.total)
  const parsedTotal = Number(activity.metadata.total)
  const totalCount = Number.isFinite(parsedTotal) ? parsedTotal : documents.length
  const visibleDocuments = documents.slice(0, 6)
  const groupedDocuments = HIT_GROUPS.map((group) => ({
    ...group,
    items: visibleDocuments.filter((document) => {
      const type = publicText(document.entity_type)
      return group.type === 'other' ? !['knowledge_point', 'question'].includes(type || '') : type === group.type
    }),
  })).filter((group) => group.items.length > 0)
  const hiddenCount = Math.max(0, totalCount - visibleDocuments.length)
  const running = activity.status === 'running'

  return (
    <li className={`inline-workflow__activity is-${activity.status}`}>
      <span className="inline-workflow__activity-icon">
        {running
          ? <LoaderCircle className="agent-chat-spin" size={13} />
          : <Database aria-hidden="true" size={13} />}
      </span>
      <div>
        <strong>{activity.title}</strong>
        {activity.detail ? <p>{activity.detail}</p> : null}
        {query || total ? (
          <dl>
            {query ? <><dt>查询内容</dt><dd>{query}</dd></> : null}
            {total ? <><dt>命中数量</dt><dd>{total}</dd></> : null}
          </dl>
        ) : null}
        {groupedDocuments.length > 0 ? (
          <div className="inline-workflow__source-groups">
            {groupedDocuments.map((group) => (
              <section className={`inline-workflow__source-group is-${group.type}`} key={group.type}>
                <div className="inline-workflow__source-group-heading">
                  <strong>{group.label}</strong>
                  <small>{group.items.length} 条摘要</small>
                </div>
                <ul className="inline-workflow__sources">
                  {group.items.map((document, index) => (
                    <HitSummary
                      document={document}
                      index={index}
                      key={publicText(document.id) || `${activity.id}_${group.type}_${index}`}
                    />
                  ))}
                </ul>
              </section>
            ))}
            {hiddenCount > 0 ? (
              <p className="inline-workflow__source-more">其余 {hiddenCount} 条命中已省略，展开结果请查看最终讲解。</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  )
}

export default function InlineWorkflow({
  workflow,
  onAnswerInput,
  onApprove,
  onReject,
  onContinueAfterFailure,
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
  const failedStep = [...workflow.steps].reverse().find((step) => step.status === 'failed')
  const retainedSummary = workflow.artifacts.length > 0
    ? `已保留 ${workflow.artifacts.length} 项结果，可展开查看。`
    : workflow.progress.completed > 0
      ? `已完成的 ${workflow.progress.completed} 个步骤仍会保留。`
      : '当前没有可确认的已保存结果。'

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

          {workflow.activities?.length > 0 ? (
            <div className="inline-workflow__activity-section">
              <span>实时执行记录</span>
              <ol>
                {workflow.activities.map((activity) => (
                  <ActivityCard activity={activity} key={activity.id} />
                ))}
              </ol>
            </div>
          ) : null}

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

          {workflow.status === 'failed' ? (
            <div className="inline-workflow__failure" role="status">
              <strong>
                <AlertCircle aria-hidden="true" size={14} />
                {failedStep ? `${failedStep.label}未完成` : '本次执行未完成'}
              </strong>
              <p>{workflow.summary || '执行过程中出现异常。'}</p>
              <small>{retainedSummary}</small>
              <button onClick={onContinueAfterFailure} type="button">
                在输入框中补充后重新发起
              </button>
            </div>
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
