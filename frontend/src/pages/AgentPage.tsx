import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowRight,
  BookOpenCheck,
  Check,
  ChevronDown,
  ChevronRight,
  FileCheck2,
  FileText,
  Lightbulb,
  ListChecks,
  MessageCircleMore,
  Paperclip,
  PanelRightOpen,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  X,
} from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { agentSources, agentSteps as mockSteps, completedAgentSteps } from '../data/fixtures'
import {
  Button,
  IconButton,
  SourceBadge,
  StatusMark,
} from '../components/Primitives'
import { useAgent, type AgentEvent } from '../store/agent-context'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type UIState = 'new' | 'ready' | 'running' | 'complete' | 'failed' | 'waiting_for_user' | 'waiting_for_approval'

interface StepView {
  id: string
  title: string
  detail: string
  duration: string
  status: 'completed' | 'running' | 'failed' | 'waiting'
}

// ---------------------------------------------------------------------------
// Helpers: map events → UI steps
// ---------------------------------------------------------------------------
function buildStepsFromEvents(events: AgentEvent[]): StepView[] {
  const steps: StepView[] = []
  const seen = new Set<string>()

  for (const event of events) {
    if (event.event_type === 'step.started') {
      const payload = event.payload as { step_id?: string; node_name?: string }
      const id = payload.step_id ?? String(event.sequence)
      if (!seen.has(id)) {
        seen.add(id)
        steps.push({
          id,
          title: payload.node_name ?? '执行步骤',
          detail: '正在执行...',
          duration: '—',
          status: 'running',
        })
      }
    } else if (event.event_type === 'step.completed') {
      const payload = event.payload as { step_id?: string; node_name?: string; output?: unknown }
      const id = payload.step_id ?? String(event.sequence)
      const idx = steps.findIndex((s) => s.id === id)
      if (idx !== -1) {
        steps[idx].status = 'completed'
        steps[idx].detail = typeof payload.output === 'string' ? payload.output : '步骤完成'
      }
    } else if (event.event_type === 'step.failed') {
      const payload = event.payload as { step_id?: string; node_name?: string; error?: string }
      const id = payload.step_id ?? String(event.sequence)
      const idx = steps.findIndex((s) => s.id === id)
      if (idx !== -1) {
        steps[idx].status = 'failed'
        steps[idx].detail = payload.error ?? '步骤失败'
      }
    }
  }
  return steps
}

function getLastMessage(events: AgentEvent[]): string | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i]
    if (event.event_type === 'message.completed') {
      const payload = event.payload as { content?: string }
      return payload.content ?? null
    }
    if (event.event_type === 'run.completed') {
      const payload = event.payload as { result?: string }
      if (payload.result) return payload.result
    }
  }
  return null
}

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

function ExecutionTrace({
  steps,
  state,
  expandedStep,
  onToggle,
}: {
  steps: StepView[]
  state: UIState
  expandedStep: string | null
  onToggle: (id: string) => void
}) {
  const displaySteps = state === 'ready'
    ? []
    : steps.length > 0
      ? steps
      : state === 'complete'
        ? completedAgentSteps
        : mockSteps
  const completedCount = displaySteps.filter((s) => s.status === 'completed').length

  return (
    <div className="execution-trace">
      <div className="execution-trace__heading">
        <div>
          <p className="eyebrow">执行轨迹</p>
          <h2>
            {state === 'complete'
              ? `${displaySteps.length} 个步骤已完成`
              : state === 'ready'
                ? '等待开始'
                : `正在处理第 ${completedCount + 1}/${displaySteps.length} 步`}
          </h2>
        </div>
        <StatusMark tone={state === 'complete' ? 'success' : state === 'ready' ? 'neutral' : 'running'}>
          {state === 'complete' ? '已完成' : state === 'ready' ? '准备就绪' : '运行中'}
        </StatusMark>
      </div>
      <div className="trace-list">
        {displaySteps.length === 0 ? (
          <p className="trace-empty">暂无执行步骤</p>
        ) : (
          displaySteps.map((step, index) => (
          <div className={`trace-step trace-step--${step.status}`} key={step.id}>
            <span className="trace-step__line" />
            <span className="trace-step__status">
              {step.status === 'completed' ? <Check size={14} /> : null}
              {step.status === 'running' ? <Sparkles size={14} /> : null}
              {step.status === 'waiting' || step.status === 'failed' ? <span /> : null}
            </span>
            <button onClick={() => onToggle(step.id)} type="button">
              <span>
                <small>{String(index + 1).padStart(2, '0')}</small>
                <strong>{step.title}</strong>
              </span>
              <span>
                <em>{step.duration}</em>
                <ChevronDown className={expandedStep === step.id ? 'is-open' : ''} size={15} />
              </span>
            </button>
            <p>{step.detail}</p>
            {expandedStep === step.id ? (
              <div className="trace-step__detail">
                <span>输入范围</span>
                <p>使用当前线程问题、关联考点和最近学习证据。</p>
                <span>结果摘要</span>
                <p>{step.detail}。此处只展示可核验的输入和结果，不展示模型私有推理。</p>
              </div>
            ) : null}
          </div>
          ))
        )}
      </div>
    </div>
  )
}

function EvidencePanel({ onClose }: { onClose?: () => void }) {
  return (
    <aside className="agent-evidence">
      <div className="agent-evidence__header">
        <div>
          <p className="eyebrow">回答依据</p>
          <h2>3 条可核验证据</h2>
        </div>
        {onClose ? (
          <IconButton label="关闭证据" onClick={onClose}>
            <X size={18} />
          </IconButton>
        ) : null}
      </div>

      <div className="evidence-list">
        {agentSources.map((source, index) => {
          const Icon =
            source.type === 'outline'
              ? FileCheck2
              : source.type === 'question'
                ? FileText
                : BookOpenCheck
          return (
            <button className={index === 1 ? 'is-active' : ''} key={source.title} type="button">
              <span className="evidence-list__index">[{index + 1}]</span>
              <span className="evidence-list__icon"><Icon size={16} /></span>
              <span className="evidence-list__content">
                <SourceBadge type={source.type}>{source.label}</SourceBadge>
                <strong>{source.title}</strong>
                <small>{source.detail}</small>
              </span>
              <ChevronRight size={16} />
            </button>
          )
        })}
      </div>

      <div className="evidence-detail">
        <div className="evidence-detail__title">
          <FileText size={18} />
          <span>
            <strong>试卷4.pdf · 第 1 题</strong>
            <small>第 1 页 · 平台已审核</small>
          </span>
        </div>
        <blockquote>
          “变量 rear 表示循环队列中队尾元素的实际位置，变量 length 表示当前循环队列中的元素个数……”
        </blockquote>
        <div className="evidence-detail__repair">
          <ShieldCheck size={16} />
          <span>
            <strong>原文恢复记录</strong>
            <small>选项 C、B、D 已从原始提取文本恢复，未使用 AI 生成内容。</small>
          </span>
        </div>
        <button className="text-command" type="button">
          打开原题
          <ArrowRight size={15} />
        </button>
      </div>

      <div className="agent-evidence__note">
        <Lightbulb size={16} />
        <span>结论中的公式由定义推导；资料用于核对题意与考点范围。</span>
      </div>
    </aside>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const suggestions = [
  '讲清楚循环队列 front 的推导',
  '根据错题生成一组专项练习',
  '检查哪些内容需要优先巩固',
]

export default function AgentPage() {
  const navigate = useNavigate()
  const { threadId } = useParams<{ threadId?: string }>()

  const {
    state: agentState,
    dispatch,
    loadThreads,
    createThread,
    createRun,
    loadThreadRuns,
    submitInput,
    connectSSE,
    disconnectSSE,
  } = useAgent()

  const [message, setMessage] = useState('')
  const [expandedStep, setExpandedStep] = useState<string | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [evidenceOpen, setEvidenceOpen] = useState(false)

  // Load threads on mount
  useEffect(() => {
    void loadThreads()
  }, [loadThreads])

  // Load thread runs when threadId changes
  useEffect(() => {
    if (!threadId) return
    loadThreadRuns(threadId).then((runs) => {
      if (runs.length > 0) {
        const latest = runs.reduce((a, b) =>
          new Date(a.created_at) > new Date(b.created_at) ? a : b,
        )
        dispatch({ type: 'SET_CURRENT_RUN', payload: latest.id })
      }
    })
  }, [threadId, loadThreadRuns, dispatch])

  // Determine UI state from run status
  const runId = agentState.currentRunId
  const run = runId ? agentState.runs[runId] : null
  const events: AgentEvent[] = runId ? agentState.events[runId] || [] : []

  const uiState: UIState = useMemo(() => {
    if (!threadId) return 'new'
    if (!run) return 'ready'
    if (run.status === 'running' || run.status === 'queued') return 'running'
    if (run.status === 'failed') return 'failed'
    if (run.status === 'waiting_for_user') return 'waiting_for_user'
    if (run.status === 'waiting_for_approval') return 'waiting_for_approval'
    return 'complete'
  }, [threadId, run])

  // Auto-expand running step
  useEffect(() => {
    if (uiState === 'running') {
      const runningStep = buildStepsFromEvents(events).find((s) => s.status === 'running')
      if (runningStep) setExpandedStep(runningStep.id)
    }
  }, [uiState, events])

  // Connect SSE when we have a running run
  useEffect(() => {
    if (runId && (run?.status === 'running' || run?.status === 'queued')) {
      connectSSE(runId)
    }
    return () => {
      if (runId && (run?.status !== 'running' && run?.status !== 'queued')) {
        disconnectSSE()
      }
    }
  }, [runId, run?.status, connectSSE, disconnectSSE])

  // Cleanup on unmount
  useEffect(() => {
    return () => { disconnectSSE() }
  }, [disconnectSSE])

  // Handle send message
  const sendMessage = useCallback(async () => {
    if (!message.trim()) return
    const input = message.trim()

    // If run is waiting for user input, submit instead of creating new run
    if (run?.status === 'waiting_for_user' && runId) {
      try {
        await submitInput(runId, input)
        setMessage('')
      } catch (e) {
        console.error('提交输入失败', e)
      }
      return
    }

    let tid = threadId
    if (!tid) {
      try {
        const thread = await createThread(input.slice(0, 50))
        tid = thread.id
        navigate(`/agent/${tid}`)
      } catch (e) {
        console.error('创建线程失败', e)
        return
      }
    }

    try {
      const newRun = await createRun(tid!, 'explain@v1', input)
      dispatch({ type: 'SET_CURRENT_RUN', payload: newRun.id })
      setMessage('')
      connectSSE(newRun.id)
    } catch (e) {
      console.error('创建运行失败', e)
    }
  }, [message, threadId, run, runId, submitInput, createThread, navigate, createRun, dispatch, connectSSE])

  // Derived data
  const currentThread = agentState.threads.find((t) => t.id === threadId)
  const lastMessage = useMemo(() => getLastMessage(events), [events])
  const steps = useMemo(() => buildStepsFromEvents(events), [events])

  const title = useMemo(() => {
    if (currentThread?.title) return currentThread.title
    if (uiState === 'waiting_for_approval') return '调整巩固优先级'
    if (uiState === 'waiting_for_user') return '等待补充信息'
    if (uiState === 'failed') return '生成专项练习'
    if (uiState === 'new') return 'Agent'
    return '对话详情'
  }, [currentThread, uiState])

  // ==================== New State ====================
  if (uiState === 'new') {
    return (
      <div className="page agent-new">
        <div className="agent-new__intro">
          <span className="agent-new__mark"><Sparkles size={21} /></span>
          <p className="eyebrow">新对话</p>
          <h1>现在最想弄清哪件事？</h1>
          <p>可以提问、粘贴题目，或直接描述你希望 Agent 完成的学习任务。</p>
        </div>
        <div className="agent-composer agent-composer--large">
          <textarea
            aria-label="输入学习问题"
            autoFocus
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') void sendMessage()
            }}
            placeholder="例如：我总是记不住循环队列里已知 rear 和 length 时 front 怎么算，能不能不要让我死记公式？"
            value={message}
          />
          <div className="agent-composer__footer">
            <IconButton label="添加题目或图片">
              <Paperclip size={18} />
            </IconButton>
            <span>⌘ Enter 发送</span>
            <Button disabled={!message.trim()} icon={<Send size={16} />} onClick={sendMessage}>
              开始
            </Button>
          </div>
        </div>
        <div className="agent-suggestions">
          <span>从常见任务开始</span>
          <div>
            {suggestions.map((suggestion) => (
              <button key={suggestion} onClick={() => setMessage(suggestion)} type="button">
                {suggestion}
                <ArrowRight size={15} />
              </button>
            ))}
          </div>
        </div>
        <div className="agent-new__boundary">
          <Search size={16} />
          <span>回答优先使用官方大纲、已审核知识与可靠原题；证据不足时会明确标记为模型推断。</span>
        </div>
      </div>
    )
  }

  // ==================== Running / Complete / Failed States ====================
  return (
    <div className="agent-workspace">
      <section className="agent-thread">
        <header className="agent-thread__header">
          <div>
            <p className="eyebrow">{currentThread?.title ?? '数据结构 · 栈和队列'}</p>
            <h1>{title}</h1>
          </div>
          <div className="agent-thread__header-actions">
            <Button
              className="agent-mobile-context"
              icon={<PanelRightOpen size={16} />}
              onClick={() => setDetailsOpen(true)}
              tone="quiet"
            >
              查看步骤
            </Button>
            <StatusMark tone={uiState === 'complete' ? 'success' : uiState === 'failed' ? 'error' : uiState === 'ready' ? 'neutral' : 'running'}>
              {uiState === 'complete' ? '已完成' : uiState === 'failed' ? '可恢复' : uiState === 'ready' ? '准备就绪' : '运行中'}
            </StatusMark>
          </div>
        </header>

        <div className="agent-timeline">
          {/* User message */}
          {uiState !== 'ready' ? (
            <article className="user-entry">
              <div className="avatar avatar--small">张</div>
              <div>
                <span>你 · 刚刚</span>
                <p>{run?.input_message ?? '正在加载...'}</p>
              </div>
            </article>
          ) : null}

          {/* Ready state */}
          {uiState === 'ready' ? (
            <article className="run-summary">
              <span className="run-summary__icon"><Sparkles size={19} /></span>
              <div>
                <p className="eyebrow">新线程</p>
                <h2>随时发送问题，Agent 会为你解答</h2>
                <p>该线程暂无运行记录。你可以在下方输入问题开始对话。</p>
              </div>
            </article>
          ) : null}

          {/* Failed state */}
          {uiState === 'failed' ? (
            <>
              <article className="run-summary run-summary--failed">
                <span className="run-summary__icon"><TriangleAlert size={19} /></span>
                <div>
                  <p className="eyebrow">运行中断 · 结果已保留</p>
                  <h2>生成逐题提示时响应超时</h2>
                  <p>大纲检索、题目筛选和 3 道练习草稿已经完成。重试只会继续失败步骤，不会重复创建练习。</p>
                  <div className="preserved-artifact">
                    <ListChecks size={18} />
                    <span>
                      <strong>专项练习草稿 · 3 道题</strong>
                      <small>已保存，可直接开始无提示练习</small>
                    </span>
                    <StatusMark tone="success">已保留</StatusMark>
                  </div>
                  <div className="run-summary__actions">
                    <Button icon={<RefreshCw size={16} />} onClick={() => { /* TODO: retry */ }}>
                      仅重试失败步骤
                    </Button>
                    <Button onClick={() => navigate('/practice/queue-check?question=1')} tone="secondary">
                      直接开始练习
                    </Button>
                  </div>
                </div>
              </article>
              <article className="agent-answer agent-answer--muted">
                <p className="eyebrow">已完成的工作</p>
                <h2>已从 18 道候选题中筛出 3 道可靠题目</h2>
                <p>每道题都通过题目质量门禁，并已关联“循环队列下标关系”考点。</p>
              </article>
            </>
          ) : null}

          {/* Running state */}
          {uiState === 'running' ? (
            <article className="run-summary">
              <span className="run-summary__icon"><Sparkles size={19} /></span>
              <div>
                <p className="eyebrow">Agent 正在工作</p>
                <h2>正在处理你的问题...</h2>
                <p>页面可以离开或刷新。该运行已保存为同一个 run，完成后会自动更新。</p>
                <button className="run-summary__progress" onClick={() => setDetailsOpen(true)} type="button">
                  <span><i style={{ width: `${Math.min(100, ((steps.filter(s => s.status === 'completed').length / Math.max(steps.length, 1)) * 100))}%` }} /></span>
                  <strong>{steps.filter(s => s.status === 'completed').length}/{steps.length}</strong>
                  <small>查看执行步骤</small>
                </button>
              </div>
            </article>
          ) : null}

          {/* Complete state */}
          {uiState === 'complete' ? (
            <article className="agent-answer">
              <div className="agent-answer__label">
                <span><Sparkles size={17} /></span>
                <strong>408 Agent</strong>
                <small>已核验 {agentSources.length} 条来源</small>
              </div>
              <section>
                <p className="eyebrow">直接结论</p>
                <h2>{lastMessage ?? '回答已生成'}</h2>
                <p>
                  {lastMessage ? '详细解答请见上方。' : '正在加载回答内容...'}
                  <button className="citation" onClick={() => setEvidenceOpen(true)} type="button">[1]</button>
                </p>
              </section>
              <div className="answer-sources">
                <span>依据</span>
                <button onClick={() => setEvidenceOpen(true)} type="button">
                  <SourceBadge type="outline">大纲</SourceBadge> 栈和队列的顺序存储
                </button>
                <button onClick={() => setEvidenceOpen(true)} type="button">
                  <SourceBadge type="question">原题</SourceBadge> 试卷4.pdf 第 1 题
                </button>
                <button onClick={() => setEvidenceOpen(true)} type="button">
                  <SourceBadge type="knowledge">知识</SourceBadge> 循环队列
                </button>
              </div>
              <div className="agent-answer__actions">
                <Button icon={<BookOpenCheck size={17} />} onClick={() => navigate('/practice/queue-check?question=1')}>
                  用 2 道题验证
                </Button>
                <Button icon={<MessageCircleMore size={17} />} tone="secondary">
                  换一种图示讲解
                </Button>
              </div>
            </article>
          ) : null}
        </div>

        {/* Composer */}
        {uiState !== 'failed' ? (
          <div className="agent-composer agent-composer--thread">
            <textarea
              aria-label="补充问题"
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') void sendMessage()
              }}
              placeholder={uiState === 'running' ? '可补充条件，Agent 会在当前步骤后处理…' : '继续追问，或让 Agent 执行下一项学习任务…'}
              rows={2}
              value={message}
            />
            <div className="agent-composer__footer">
              <IconButton label="添加题目或图片"><Paperclip size={18} /></IconButton>
              <span>{uiState === 'running' ? '运行不会因离开页面而中断' : '引用当前线程上下文'}</span>
              <IconButton label="发送消息" onClick={sendMessage}><Send size={18} /></IconButton>
            </div>
          </div>
        ) : null}
      </section>

      {/* Right context panel */}
      <aside className="agent-context">
        <ExecutionTrace
          expandedStep={expandedStep}
          onToggle={(id) => setExpandedStep((current) => (current === id ? null : id))}
          state={uiState}
          steps={steps}
        />
        {uiState === 'complete' ? (
          <button className="context-evidence-link" onClick={() => setEvidenceOpen(true)} type="button">
            <span><FileCheck2 size={18} /></span>
            <span>
              <strong>查看回答证据</strong>
              <small>3 条来源 · 1 条原题修复记录</small>
            </span>
            <ChevronRight size={16} />
          </button>
        ) : null}
      </aside>

      {/* Evidence drawer */}
      {evidenceOpen ? (
        <>
          <button aria-label="关闭证据遮罩" className="drawer-backdrop" onClick={() => setEvidenceOpen(false)} type="button" />
          <div className="evidence-drawer"><EvidencePanel onClose={() => setEvidenceOpen(false)} /></div>
        </>
      ) : null}

      {/* Steps drawer (mobile) */}
      {detailsOpen ? (
        <>
          <button aria-label="关闭步骤遮罩" className="drawer-backdrop" onClick={() => setDetailsOpen(false)} type="button" />
          <div className="context-drawer">
            <div className="context-drawer__header">
              <strong>执行步骤</strong>
              <IconButton label="关闭步骤" onClick={() => setDetailsOpen(false)}><X size={18} /></IconButton>
            </div>
            <ExecutionTrace
              expandedStep={expandedStep}
              onToggle={(id) => setExpandedStep((current) => (current === id ? null : id))}
              state={uiState}
              steps={steps}
            />
          </div>
        </>
      ) : null}
    </div>
  )
}
