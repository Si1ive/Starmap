import { useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Bookmark,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  Clock3,
  Expand,
  FileText,
  Image as ImageIcon,
  Lightbulb,
  Minus,
  Plus,
  RotateCcw,
  Save,
  X,
  XCircle,
} from 'lucide-react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { queueQuestion } from '../data/fixtures'
import { Button, Formula, IconButton, SourceBadge, StatusMark } from '../components/Primitives'

const processorPrompt = `44. 下图所示的处理机逻辑框图中，有两条独立的总线和两个独立的存储器。已知指令存储器 IM 最大容量为 16384 字（字长 18 位），数据存储器 DM 最大容量为 65536 字（字长 16 位），各寄存器均有“打入”和“送出”控制命令。

（1）请指出程序计数器 PC、指令寄存器 IR、累加器 AC0 和 AC1、通用寄存器 R0-R7、IAR、IDR、DAR、DDR 的位数。

（2）设处理机的加法指令为 ADD X(Ri)，其功能为 (AC0)+((Ri)+X)→AC1。试画出 ADD 指令从取指开始到执行结束的操作序列图，写明基本操作步骤和相应微操作控制信号。`

const rubric = [
  {
    title: '寄存器位数',
    score: '4 / 4',
    state: 'complete',
    summary: 'PC、IAR、IR、AC、DAR 和数据寄存器位数均判断正确。',
    detail: 'IM 有 16384=2^14 个地址，故 PC 与 IAR 为 14 位；指令字长 18 位，IR 与 IDR 为 18 位；DM 地址为 16 位，DAR 为 16 位；数据字长 16 位，AC0、AC1、R0-R7 与 DDR 为 16 位。',
  },
  {
    title: '取指阶段微操作',
    score: '2 / 3',
    state: 'partial',
    summary: '取指顺序正确，但遗漏了 IDR 送出到 IR 的控制信号。',
    detail: '参考要求包含：PCout, IARin；IMread；IDRout, IRin；PC+1→PC。你的答案写出了前三个基本步骤，但第二次总线传送没有标记 IDRout。',
  },
  {
    title: '执行阶段与有效地址',
    score: '1 / 5',
    state: 'missing',
    summary: '写出了 Ri+X，但未完成访存和 AC1 写回。',
    detail: '还需要把有效地址送入 DAR，发出 DMread，将 DDR 与 AC0 送入 ALU，并把结果写入 AC1。建议按“地址形成—访存—运算—写回”四段重写。',
  },
]

export default function PracticePage() {
  const navigate = useNavigate()
  const { sessionId, view } = useParams()
  const [searchParams] = useSearchParams()
  const [selected, setSelected] = useState<string | null>(null)
  const [mistakeReason, setMistakeReason] = useState('条件遗漏')
  const [answers, setAnswers] = useState({ part1: '', part2: '' })
  const [imageOpen, setImageOpen] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [expandedRubric, setExpandedRubric] = useState(0)
  const isProcessor = sessionId === 'processor'
  const isFeedback = view === 'feedback'
  const questionPosition = searchParams.get('question') ?? '1'

  const closeImage = () => {
    setImageOpen(null)
    setZoom(1)
  }

  if (isProcessor) {
    return (
      <div className="practice-shell">
        <header className="practice-topbar">
          <IconButton label="退出练习" onClick={() => navigate('/today')}>
            <X size={20} />
          </IconButton>
          <div className="practice-progress">
            <span>主观题专项</span>
            <strong>第 {questionPosition} / 1 题</strong>
          </div>
          <div className="practice-topbar__actions">
            <span className="autosave"><Save size={15} /> 已保存 11:42</span>
            <IconButton label="标记不确定"><Bookmark size={19} /></IconButton>
          </div>
        </header>

        {!isFeedback ? (
          <>
            <main className="subjective-workspace">
              <section className="subjective-question">
                <div className="question-kicker">
                  <SourceBadge type="question">原题</SourceBadge>
                  <span>计算机组成原理 · 处理器</span>
                  <span>12 分</span>
                </div>
                <h1>处理机数据通路与 ADD 指令微操作</h1>
                <div className="long-stem">
                  {processorPrompt.split('\n').map((paragraph, index) => (
                    <p key={`processor-paragraph-${index}`}>{paragraph}</p>
                  ))}
                </div>
                <div className="question-assets">
                  <button onClick={() => setImageOpen('/assets/instruction-format.jpg')} type="button">
                    <img alt="ADD 指令格式图" src="/assets/instruction-format.jpg" />
                    <span><ImageIcon size={16} /> 指令格式 <Expand size={15} /></span>
                  </button>
                  <button onClick={() => setImageOpen('/assets/processor-diagram.jpg')} type="button">
                    <img alt="双总线处理机逻辑框图" src="/assets/processor-diagram.jpg" />
                    <span><ImageIcon size={16} /> 处理机逻辑框图 <Expand size={15} /></span>
                  </button>
                </div>
              </section>

              <section className="subjective-answer">
                <div className="answer-section">
                  <div className="answer-section__heading">
                    <span>01</span>
                    <div>
                      <h2>各寄存器位数</h2>
                      <p>按寄存器分组写出位数，并说明地址位数的计算依据。</p>
                    </div>
                  </div>
                  <textarea
                    aria-label="第一小问答案"
                    onChange={(event) => setAnswers((current) => ({ ...current, part1: event.target.value }))}
                    placeholder="例如：IM 最大容量为 16384=2^14 字，因此 PC 和 IAR..."
                    value={answers.part1}
                  />
                </div>
                <div className="answer-section">
                  <div className="answer-section__heading">
                    <span>02</span>
                    <div>
                      <h2>ADD 指令操作序列</h2>
                      <p>按取指、地址形成、访存、运算和写回分步作答。</p>
                    </div>
                  </div>
                  <textarea
                    aria-label="第二小问答案"
                    onChange={(event) => setAnswers((current) => ({ ...current, part2: event.target.value }))}
                    placeholder={'T0: PCout, IARin\nT1: IMread...'}
                    value={answers.part2}
                  />
                </div>
              </section>
            </main>

            <footer className="practice-footer">
              <Button icon={<ChevronLeft size={17} />} onClick={() => navigate('/agent/queue?state=complete')} tone="quiet">
                返回讲解
              </Button>
              <div>
                <span>草稿按小问自动保存</span>
                <Button
                  disabled={!answers.part1.trim() && !answers.part2.trim()}
                  icon={<ArrowRight size={17} />}
                  onClick={() => navigate('/practice/processor/feedback?question=1')}
                >
                  提交评分
                </Button>
              </div>
            </footer>
          </>
        ) : (
          <main className="subjective-feedback">
            <section className="feedback-summary feedback-summary--subjective">
              <div className="feedback-summary__score">
                <strong>7</strong>
                <span>/ 12 分</span>
              </div>
              <div>
                <p className="eyebrow">按评分点反馈</p>
                <h1>寄存器位数掌握稳定，执行阶段还没有闭合。</h1>
                <p>反馈只对照当前评分点，不声称等同人工阅卷。重点补齐访存、运算与写回控制信号。</p>
              </div>
            </section>

            <section className="rubric-panel">
              <div className="rubric-panel__heading">
                <div>
                  <h2>评分点</h2>
                  <p>点击展开你的答案片段、参考要求与下一步建议。</p>
                </div>
                <StatusMark tone="warning">2 项需补充</StatusMark>
              </div>
              <div className="rubric-list">
                {rubric.map((item, index) => (
                  <div className={`rubric-item rubric-item--${item.state}`} key={item.title}>
                    <button onClick={() => setExpandedRubric(expandedRubric === index ? -1 : index)} type="button">
                      <span className="rubric-item__status">
                        {item.state === 'complete' ? <Check size={15} /> : item.state === 'partial' ? '½' : '!'}
                      </span>
                      <span>
                        <strong>{item.title}</strong>
                        <small>{item.summary}</small>
                      </span>
                      <em>{item.score}</em>
                      <ChevronDown className={expandedRubric === index ? 'is-open' : ''} size={17} />
                    </button>
                    {expandedRubric === index ? (
                      <div className="rubric-item__detail">
                        <span>参考要求</span>
                        <p>{item.detail}</p>
                        <span>你的答案片段</span>
                        <blockquote>
                          {index === 0
                            ? 'PC、IAR 是 14 位；IR、IDR 是 18 位；AC0、AC1、R0-R7、DAR、DDR 都是 16 位。'
                            : index === 1
                              ? 'T0: PC→IAR；T1: 读 IM；T2: IDR→IR；PC+1→PC。'
                              : 'Ri+X 得到有效地址。'}
                        </blockquote>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </section>

            <section className="feedback-next">
              <Lightbulb size={20} />
              <div>
                <strong>下一次只练“地址形成—访存—写回”</strong>
                <p>Agent 已准备一道缩短版微操作题，不重复考查寄存器位数。</p>
              </div>
              <Button icon={<ArrowRight size={17} />}>开始补强题</Button>
            </section>
          </main>
        )}

        {imageOpen ? (
          <div className="image-viewer" role="dialog" aria-label="题图查看器" aria-modal="true">
            <header>
              <span>原题题图</span>
              <div>
                <IconButton label="缩小图片" onClick={() => setZoom((value) => Math.max(0.6, value - 0.2))}>
                  <Minus size={19} />
                </IconButton>
                <span>{Math.round(zoom * 100)}%</span>
                <IconButton label="放大图片" onClick={() => setZoom((value) => Math.min(2.4, value + 0.2))}>
                  <Plus size={19} />
                </IconButton>
                <IconButton label="关闭题图" onClick={closeImage}><X size={20} /></IconButton>
              </div>
            </header>
            <div className="image-viewer__canvas">
              <img alt="放大的原题题图" src={imageOpen} style={{ transform: `scale(${zoom})` }} />
            </div>
          </div>
        ) : null}
      </div>
    )
  }

  if (isFeedback) {
    return (
      <div className="practice-shell">
        <header className="practice-topbar">
          <IconButton label="退出反馈" onClick={() => navigate('/agent/queue?state=complete')}>
            <X size={20} />
          </IconButton>
          <div className="practice-progress">
            <span>验证题反馈</span>
            <strong>第 1 / 2 题</strong>
          </div>
          <span className="practice-timer"><Clock3 size={16} /> 用时 46 秒</span>
        </header>

        <main className="objective-feedback">
          <section className="objective-feedback__result">
            <span className="result-icon result-icon--wrong"><XCircle size={28} /></span>
            <div>
              <p className="eyebrow">回答错误 · 你的答案 B · 正确答案 C</p>
              <h1>你少考虑了“队尾元素本身”。</h1>
              <p>
                length 个元素之间只有 length−1 个位置间隔，因此应从 rear 向前退 length−1 步。
              </p>
            </div>
          </section>

          <section className="answer-comparison">
            <div>
              <span>你的计算</span>
              <Formula>{'(rear-length+m) \\bmod m'}</Formula>
            </div>
            <ArrowRight size={20} />
            <div>
              <span>正确关系</span>
              <Formula>{'(rear-length+1+m) \\bmod m'}</Formula>
            </div>
          </section>

          <section className="reason-confirmation">
            <div>
              <p className="eyebrow">确认错因</p>
              <h2>这次错误更接近哪一种？</h2>
              <p>确认后只会影响后续复习题型和间隔，可以在错题页修改。</p>
            </div>
            <div className="reason-options">
              {['条件遗漏', '公式记混', '计算失误', '题意理解'].map((reason) => (
                <button
                  className={mistakeReason === reason ? 'is-selected' : ''}
                  key={reason}
                  onClick={() => setMistakeReason(reason)}
                  type="button"
                >
                  <span>{mistakeReason === reason ? <Check size={15} /> : null}</span>
                  <strong>{reason}</strong>
                  {reason === '条件遗漏' ? <small>少考虑 length 包含队尾本身</small> : null}
                </button>
              ))}
            </div>
          </section>

          <section className="feedback-explanation">
            <details>
              <summary>
                <span><FileText size={17} /> 展开完整解析与选项分析</span>
                <ChevronDown size={17} />
              </summary>
              <div>
                <p>设 rear=2，length=3，队列元素占据下标 0、1、2。front 应为 0，因此：</p>
                <Formula>{'(2-3+1+m) \\bmod m = 0'}</Formula>
                <p>B 选项多退了一步，会落到队首前一个空位置。</p>
              </div>
            </details>
          </section>

          <div className="objective-feedback__actions">
            <Button
              icon={<CheckCircle2 size={17} />}
              onClick={() => navigate(`/mistakes?new=queue&reason=${encodeURIComponent(mistakeReason)}`)}
            >
              记录错因并安排复习
            </Button>
            <Button icon={<ArrowRight size={17} />} tone="secondary">继续第 2 题</Button>
          </div>
        </main>
      </div>
    )
  }

  return (
    <div className="practice-shell">
      <header className="practice-topbar">
        <IconButton label="退出练习" onClick={() => navigate('/agent/queue?state=complete')}>
          <X size={20} />
        </IconButton>
        <div className="practice-progress">
          <span>循环队列验证</span>
          <strong>第 {questionPosition} / 2 题</strong>
          <span className="practice-progress__bar"><i style={{ width: '50%' }} /></span>
        </div>
        <div className="practice-topbar__actions">
          <span className="practice-timer"><Clock3 size={16} /> 00:36</span>
          <IconButton label="标记不确定"><Bookmark size={19} /></IconButton>
        </div>
      </header>

      <main className="objective-workspace">
        <section className="question-paper">
          <div className="question-paper__meta">
            <span>单选题</span>
            <span>数据结构 · 循环队列</span>
          </div>
          <span className="question-number">01</span>
          <h1>{queueQuestion.stem}</h1>
          <div className="option-list">
            {queueQuestion.options.map((option) => (
              <button
                className={selected === option.key ? 'is-selected' : ''}
                key={option.key}
                onClick={() => setSelected(option.key)}
                type="button"
              >
                <span>{option.key}</span>
                <strong>{option.text}</strong>
                <i>{selected === option.key ? <Check size={16} /> : null}</i>
              </button>
            ))}
          </div>
          <div className="question-paper__source">
            <SourceBadge type="question">原题</SourceBadge>
            <span>试卷4.pdf · 第 1 题</span>
            <span>选项经原文恢复并审核</span>
          </div>
        </section>
      </main>

      <footer className="practice-footer">
        <Button icon={<ArrowLeft size={17} />} onClick={() => navigate('/agent/queue?state=complete')} tone="quiet">
          返回讲解
        </Button>
        <div>
          <Button icon={<RotateCcw size={16} />} onClick={() => setSelected(null)} tone="quiet">清除选择</Button>
          <Button
            disabled={!selected}
            icon={<ArrowRight size={17} />}
            onClick={() => navigate('/practice/queue-check/feedback?question=1')}
          >
            提交答案
          </Button>
        </div>
      </footer>
    </div>
  )
}
