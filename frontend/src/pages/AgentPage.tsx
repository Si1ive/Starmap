import { useEffect, useMemo, useState } from 'react'
import {
  ArrowRight,
  BookOpenCheck,
  Check,
  ChevronDown,
  ChevronRight,
  CircleStop,
  FileCheck2,
  FileText,
  History,
  Lightbulb,
  ListChecks,
  MessageCircleMore,
  Paperclip,
  PanelRightOpen,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  X,
} from 'lucide-react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { agentHistory, agentSources, agentSteps, completedAgentSteps } from '../data/fixtures'
import {
  Button,
  Formula,
  IconButton,
  PageHeading,
  SourceBadge,
  StatusMark,
} from '../components/Primitives'

type AgentState = 'new' | 'running' | 'complete' | 'failed' | 'approval'

const suggestions = [
  '讲清楚循环队列 front 的推导',
  '根据错题生成一组专项练习',
  '检查哪些内容需要优先巩固',
]

const sourceIcons = {
  outline: FileCheck2,
  question: FileText,
  knowledge: BookOpenCheck,
}

function ExecutionTrace({
  state,
  expandedStep,
  onToggle,
}: {
  state: AgentState
  expandedStep: string | null
  onToggle: (id: string) => void
}) {
  const steps = state === 'complete' ? completedAgentSteps : agentSteps

  return (
    <div className="execution-trace">
      <div className="execution-trace__heading">
        <div>
          <p className="eyebrow">执行轨迹</p>
          <h2>{state === 'complete' ? '6 个步骤已完成' : '正在处理第 5/6 步'}</h2>
        </div>
        <StatusMark tone={state === 'complete' ? 'success' : 'running'}>
          {state === 'complete' ? '已完成' : '运行中'}
        </StatusMark>
      </div>
      <div className="trace-list">
        {steps.map((step, index) => (
          <div className={`trace-step trace-step--${step.status}`} key={step.id}>
            <span className="trace-step__line" />
            <span className="trace-step__status">
              {step.status === 'completed' ? <Check size={14} /> : null}
              {step.status === 'running' ? <Sparkles size={14} /> : null}
              {step.status === 'waiting' ? <span /> : null}
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
                <p>
                  {step.id === 'knowledge'
                    ? '仅检索已审核知识、官方大纲与质量达标的原题。'
                    : '使用当前线程问题、关联考点和最近学习证据。'}
                </p>
                <span>结果摘要</span>
                <p>{step.detail}。此处只展示可核验的输入和结果，不展示模型私有推理。</p>
              </div>
            ) : null}
          </div>
        ))}
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
          const Icon = sourceIcons[source.type as keyof typeof sourceIcons]
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

export default function AgentPage() {
  const navigate = useNavigate()
  const { threadId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryState = searchParams.get('state') as AgentState | null
  const state: AgentState = threadId ? queryState ?? 'complete' : 'new'
  const evidenceOpen = searchParams.get('evidence') === '1'
  const historyItem = agentHistory.find((item) => item.id === threadId)
  const [message, setMessage] = useState('')
  const [expandedStep, setExpandedStep] = useState<string | null>(state === 'running' ? 'knowledge' : null)
  const [approvalRejected, setApprovalRejected] = useState(false)
  const [detailsOpen, setDetailsOpen] = useState(false)

  useEffect(() => {
    if (state !== 'running' || searchParams.get('hold') === '1') return undefined

    const timer = window.setTimeout(() => {
      navigate(`/agent/${threadId ?? 'queue'}?state=complete`, { replace: true })
    }, 1800)

    return () => window.clearTimeout(timer)
  }, [navigate, searchParams, state, threadId])

  const title = useMemo(() => {
    if (historyItem) return historyItem.title
    if (state === 'approval') return '调整巩固优先级'
    if (state === 'failed') return '生成 20 题专项练习'
    if (state === 'new') return 'Agent'
    return '循环队列的 front 怎么算'
  }, [historyItem, state])

  const openEvidence = () => {
    const next = new URLSearchParams(searchParams)
    next.set('evidence', '1')
    setSearchParams(next)
  }

  const closeEvidence = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('evidence')
    setSearchParams(next)
  }

  const sendMessage = () => {
    if (!message.trim()) return
    navigate('/agent/queue?state=running')
  }

  if (state === 'new') {
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
              if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') sendMessage()
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

  if (state === 'approval') {
    return (
      <div className="page agent-page">
        <PageHeading
          actions={<StatusMark tone={approvalRejected ? 'neutral' : 'warning'}>{approvalRejected ? '已拒绝' : '等待确认'}</StatusMark>}
          description="Agent 发现“操作系统 · 死锁”连续错误 3 次，建议提高该考点的巩固优先级。"
          eyebrow="学习建议 · 内容调整"
          title={title}
        />

        <section className="approval-sheet">
          <div className="approval-sheet__why">
            <span><Sparkles size={18} /></span>
            <div>
              <h2>{approvalRejected ? '原优先级保持不变' : '这次修改会改变什么'}</h2>
              <p>
                {approvalRejected
                  ? '拒绝后没有改变内容优先级。你仍可重新打开差异并决定是否采用。'
                  : '只调整两个考点的相对优先级，不创建学习时间表，也不会改变已有完成记录。'}
              </p>
            </div>
          </div>

          {!approvalRejected ? (
            <div className="approval-diff">
              <div className="approval-diff__column">
                <span>当前优先级</span>
                <div className="approval-diff__item approval-diff__item--remove">
                  <small>优先巩固</small>
                  <strong>数据结构排序练习</strong>
                  <em>下调</em>
                </div>
              </div>
              <ArrowRight className="approval-diff__arrow" size={22} />
              <div className="approval-diff__column">
                <span>建议优先级</span>
                <div className="approval-diff__item approval-diff__item--add">
                  <small>优先巩固</small>
                  <strong>操作系统死锁专项</strong>
                  <em>上调</em>
                </div>
              </div>
            </div>
          ) : (
            <div className="approval-rejected">
              <History size={20} />
              <span>
                <strong>内容顺序保持不变</strong>
                <small>Agent 会继续根据后续对话和练习记录更新建议</small>
              </span>
            </div>
          )}

          <div className="approval-impact">
            <span><ShieldCheck size={17} /> 不会删除历史记录</span>
            <span><RotateCcw size={17} /> 可随时在对话中调整</span>
            <span><CircleStop size={17} /> 拒绝不会中断当前线程</span>
          </div>

          <div className="approval-sheet__actions">
            {approvalRejected ? (
              <>
                <Button onClick={() => navigate('/progress')} tone="quiet">查看学习进度</Button>
                <Button icon={<RefreshCw size={16} />} onClick={() => setApprovalRejected(false)} tone="secondary">
                  重新打开差异
                </Button>
              </>
            ) : (
              <>
                <Button onClick={() => setApprovalRejected(true)} tone="secondary">保持当前顺序</Button>
                <Button icon={<Check size={16} />} onClick={() => navigate('/progress')}>
                  采用调整
                </Button>
              </>
            )}
          </div>
        </section>
      </div>
    )
  }

  return (
    <div className="agent-workspace">
      <section className="agent-thread">
        <header className="agent-thread__header">
          <div>
            <p className="eyebrow">{historyItem?.subject ?? '数据结构 · 栈和队列'}</p>
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
            <StatusMark tone={state === 'complete' ? 'success' : state === 'failed' ? 'error' : 'running'}>
              {state === 'complete' ? '已完成' : state === 'failed' ? '可恢复' : '运行中'}
            </StatusMark>
          </div>
        </header>

        <div className="agent-timeline">
          <article className="user-entry">
            <div className="avatar avatar--small">张</div>
            <div>
              <span>你 · 刚刚</span>
              <p>我总是记不住循环队列里已知 rear 和 length 时 front 怎么算，能不能不要让我死记公式？</p>
            </div>
          </article>

          {state === 'failed' ? (
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
                    <Button
                      icon={<RefreshCw size={16} />}
                      onClick={() => navigate('/agent/recovery?state=running')}
                    >
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

          {state === 'running' ? (
            <article className="run-summary">
              <span className="run-summary__icon"><Sparkles size={19} /></span>
              <div>
                <p className="eyebrow">Agent 正在工作</p>
                <h2>正在核对 rear 的定义，再组织不依赖死记的推导</h2>
                <p>页面可以离开或刷新。该运行已保存为同一个 run，完成后会从任务中心回到这里。</p>
                <button className="run-summary__progress" onClick={() => setDetailsOpen(true)} type="button">
                  <span><i style={{ width: '72%' }} /></span>
                  <strong>4/6</strong>
                  <small>查看执行步骤</small>
                </button>
              </div>
            </article>
          ) : null}

          {state === 'complete' ? (
            <article className="agent-answer">
              <div className="agent-answer__label">
                <span><Sparkles size={17} /></span>
                <strong>408 Agent</strong>
                <small>已核验 3 条来源</small>
              </div>
              <section>
                <p className="eyebrow">直接结论</p>
                <h2>从 rear 向前退 <Formula>length-1</Formula> 步，就是队首。</h2>
                <p>
                  因为题目把 <strong>rear 定义为队尾元素当前所在位置</strong>。队列一共有 length 个元素，
                  从最后一个元素退到第一个元素，只需要跨过 length−1 个间隔。
                  <button className="citation" onClick={openEvidence} type="button">[1]</button>
                </p>
              </section>
              <div className="derivation">
                <span className="derivation__margin">推导</span>
                <div>
                  <p>先写出不考虑数组回绕时的位置：</p>
                  <Formula>{'front = rear - (length - 1)'}</Formula>
                  <p>再把减法整理，并用加 m 避免负下标：</p>
                  <Formula>{'front = (rear - length + 1 + m) \\bmod m'}</Formula>
                </div>
              </div>
              <section className="mistake-callout">
                <Lightbulb size={18} />
                <div>
                  <strong>最容易少掉的“1”来自哪里？</strong>
                  <p>length 计算时包含队尾本身，所以从 rear 往前移动的次数是 length−1，而不是 length。</p>
                </div>
              </section>
              <div className="answer-sources">
                <span>依据</span>
                <button onClick={openEvidence} type="button"><SourceBadge type="outline">大纲</SourceBadge> 栈和队列的顺序存储</button>
                <button onClick={openEvidence} type="button"><SourceBadge type="question">原题</SourceBadge> 试卷4.pdf 第 1 题</button>
                <button onClick={openEvidence} type="button"><SourceBadge type="knowledge">知识</SourceBadge> 循环队列</button>
              </div>
              <div className="agent-answer__actions">
                <Button
                  icon={<BookOpenCheck size={17} />}
                  onClick={() => navigate('/practice/queue-check?question=1')}
                >
                  用 2 道题验证
                </Button>
                <Button icon={<MessageCircleMore size={17} />} tone="secondary">
                  换一种图示讲解
                </Button>
              </div>
            </article>
          ) : null}
        </div>

        {state !== 'failed' ? (
          <div className="agent-composer agent-composer--thread">
            <textarea
              aria-label="补充问题"
              onChange={(event) => setMessage(event.target.value)}
              placeholder={state === 'running' ? '可补充条件，Agent 会在当前步骤后处理…' : '继续追问，或让 Agent 执行下一项学习任务…'}
              rows={2}
              value={message}
            />
            <div className="agent-composer__footer">
              <IconButton label="添加题目或图片"><Paperclip size={18} /></IconButton>
              <span>{state === 'running' ? '运行不会因离开页面而中断' : '引用当前线程上下文'}</span>
              <IconButton label="发送消息"><Send size={18} /></IconButton>
            </div>
          </div>
        ) : null}
      </section>

      <aside className="agent-context">
        <ExecutionTrace
          expandedStep={expandedStep}
          onToggle={(id) => setExpandedStep((current) => (current === id ? null : id))}
          state={state}
        />
        {state === 'complete' ? (
          <button className="context-evidence-link" onClick={openEvidence} type="button">
            <span><FileCheck2 size={18} /></span>
            <span>
              <strong>查看回答证据</strong>
              <small>3 条来源 · 1 条原题修复记录</small>
            </span>
            <ChevronRight size={16} />
          </button>
        ) : null}
      </aside>

      {evidenceOpen ? (
        <>
          <button aria-label="关闭证据遮罩" className="drawer-backdrop" onClick={closeEvidence} type="button" />
          <div className="evidence-drawer"><EvidencePanel onClose={closeEvidence} /></div>
        </>
      ) : null}

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
              state={state}
            />
          </div>
        </>
      ) : null}
    </div>
  )
}
