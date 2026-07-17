import {
  FormEvent,
  PointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import {
  AlertCircle,
  ArrowDown,
  ArrowRight,
  BookOpenCheck,
  CalendarCheck2,
  Check,
  Clock3,
  Eye,
  EyeOff,
  FileCheck2,
  Lock,
  Mail,
  MessageCircleMore,
  Search,
  ShieldCheck,
  Sparkles,
  UserRound,
  X,
} from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  AuthApiError,
  postLoginPath,
  registerWithPassword,
} from '../auth'
import useAuth from '../useAuth'

type AuthMode = 'login' | 'register'
type StageId = 'question' | 'evidence' | 'practice' | 'review'

const STAGE_HOLD_MS = 5600
const STAGE_TRAVEL_MS = 1600
const thoughtProfileUrl = new URL('../login-thought-profile.png', import.meta.url).href

const learningStages = [
  {
    id: 'question',
    index: '01',
    label: '主动追问',
    title: '先确认你卡在哪一步',
    description: '不急着给公式。Agent 先判断你混淆的是指针约定、环形下标，还是推导过程。',
    meta: '正在缩小问题范围',
    icon: MessageCircleMore,
  },
  {
    id: 'evidence',
    index: '02',
    label: '精准诊断',
    title: '把“不会”定位成具体缺口',
    description: '结合你的作答过程、知识点关系和题型特征，继续追问，直到确认真正缺失的那一环。',
    meta: '已锁定知识与题型缺口',
    icon: Search,
  },
  {
    id: 'practice',
    index: '03',
    label: '针对训练',
    title: '用合适的题把缺口补上',
    description: '匹配真题与模拟题进行演练，再把错误过程整理成下一次可以复用的解题总结。',
    meta: '训练内容已匹配',
    icon: BookOpenCheck,
  },
  {
    id: 'review',
    index: '04',
    label: '记忆巩固',
    title: '在遗忘前再次想起来',
    description: '本次错因进入记忆轨迹，在保持率越过临界线前打开下一次主动回忆窗口。',
    meta: '下一窗口已进入日程',
    icon: CalendarCheck2,
  },
] as const

const routeSegments = [
  'M70 105C220 35 420 90 510 170',
  'M510 170C600 252 390 292 445 360',
  'M445 360C500 430 650 405 760 465',
] as const

const diagnosticQuestions = [
  {
    id: 'ring',
    short: '环形下标',
    question: 'rear 比 front 小时，你认为发生了什么？',
    result: '问题出在数组回绕',
    detail: '你已经理解队列操作，但还没有把越过数组边界后的回绕关系纳入计算。',
  },
  {
    id: 'derive',
    short: '推导过程',
    question: '不看公式，你能画出一次入队过程吗？',
    result: '从操作过程重建公式',
    detail: '与其继续背结论，更有效的下一步是从队列长度和指针位置重新推导。',
  },
  {
    id: 'convention',
    short: '指针约定',
    question: 'rear 指向队尾元素，还是下一个空位？',
    result: '先确认题目的 rear 约定',
    detail: '同一个 front 公式会随 rear 的定义改变。先统一约定，推导才不会从第一步就偏离。',
  },
] as const

const evidenceSources = [
  {
    id: 'exam',
    label: '作答过程',
    code: '本次对话 · 第 2 轮',
    title: '能复述公式，但无法解释 +m',
    location: '诊断信号 · 作答轨迹',
    excerpt: '诊断前只知道“循环队列公式总是记错”；追问后发现，你能写出公式，却说不清负下标为什么需要回绕。',
  },
  {
    id: 'knowledge',
    label: '知识关系',
    code: 'DS-2.3 → DS-2.4',
    title: '取模运算未迁移到环形下标',
    location: '知识库依据 · 前置关系',
    excerpt: '知识库显示，“循环队列长度计算”依赖“取模与环形下标”。你的前置知识会算取模，但没有迁移到数组回绕场景。',
  },
  {
    id: 'outline',
    label: '题型特征',
    code: '近 5 年 · 7 道同类题',
    title: '遇到指针回绕条件时连续失分',
    location: '题库依据 · 错误模式',
    excerpt: '同类题对比表明：不发生回绕时你能答对，一旦 rear 小于 front 就会误判，缺口集中在“环形关系识别”。',
  },
] as const

const practiceVariants = [
  {
    id: 'condition',
    label: '真题演练',
    note: '匹配相同知识缺口的历年真题',
    question: '容量为 8，front = 6，rear = 2，rear 指向队尾元素。当前队列长度是多少？',
    options: ['3', '5', '6', '7'],
    correct: 1,
  },
  {
    id: 'convention',
    label: '模拟强化',
    note: '更换指针约定，检查知识迁移',
    question: '如果 rear 改为指向下一个空位，原有长度公式最需要调整的是哪一部分？',
    options: ['取模运算', '是否包含队尾本身', '数组容量 m', 'front 的取值范围'],
    correct: 1,
  },
  {
    id: 'trap',
    label: '总结复盘',
    note: '从本轮错因中提炼可复用判断',
    question: '下面哪项最能解释公式中 “+m” 的作用？',
    options: ['扩大队列容量', '避免差值为负', '让 rear 自动加一', '记录队列长度'],
    correct: 1,
  },
] as const

const reviewWindows = [
  {
    id: 'record',
    time: '现在',
    retention: 92,
    chartX: 45,
    chartY: 72,
    title: '记录真实错因',
    detail: '不是“粗心”，而是遗漏了 rear 指向队尾元素这一条件。',
  },
  {
    id: 'recall',
    time: '明天 19:30',
    retention: 58,
    chartX: 292,
    chartY: 222,
    title: '第一次主动回忆',
    detail: '先不看讲解，重新推导公式，再完成一道同考点变式题。',
  },
  {
    id: 'verify',
    time: '3 天后',
    retention: 64,
    chartX: 548,
    chartY: 205,
    title: '更换题型再验证',
    detail: '改变指针约定，确认你掌握的是关系，而不是记住一道题。',
  },
] as const

function BrandContent() {
  return (
    <>
      <span className="platform-brand__mark" aria-hidden="true">
        <svg viewBox="0 0 54 44">
          <g transform="translate(0 44) scale(1 -1)">
            <path d="M5 34C12 7 23 9 22 23C21 36 33 38 35 22C37 8 45 8 50 13" />
            <circle className="mark-node mark-node--one" cx="5" cy="34" r="3.1" />
            <circle className="mark-node mark-node--two" cx="22" cy="23" r="3.1" />
            <circle className="mark-node mark-node--three" cx="35" cy="22" r="3.1" />
            <circle className="mark-node mark-node--four" cx="50" cy="13" r="3.1" />
          </g>
        </svg>
      </span>
      <span className="platform-brand__name">
        <b>408</b>
        <strong>学习工作台</strong>
      </span>
    </>
  )
}

export default function LoginPage() {
  const { login } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const heroRef = useRef<HTMLElement>(null)
  const arrivalTimerRef = useRef<number | null>(null)
  const [activeStage, setActiveStage] = useState<StageId>('question')
  const [destinationStage, setDestinationStage] = useState<StageId>('question')
  const [stageMoving, setStageMoving] = useState(false)
  const [activeDiagnostic, setActiveDiagnostic] = useState(0)
  const [activeSource, setActiveSource] = useState('exam')
  const [activeVariant, setActiveVariant] = useState(0)
  const [selectedAnswer, setSelectedAnswer] = useState<number | null>(null)
  const [activeReviewWindow, setActiveReviewWindow] = useState(1)
  const [authOpen, setAuthOpen] = useState(false)
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [passwordVisible, setPasswordVisible] = useState(false)
  const [rememberLogin, setRememberLogin] = useState(true)
  const [authError, setAuthError] = useState('')
  const [authNotice, setAuthNotice] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const currentStage =
    learningStages.find((stage) => stage.id === activeStage) ?? learningStages[0]
  const currentStageIndex = learningStages.findIndex((stage) => stage.id === activeStage)
  const destinationStageIndex = learningStages.findIndex(
    (stage) => stage.id === destinationStage,
  )
  const traceStageIndex =
    stageMoving && destinationStageIndex > currentStageIndex
      ? destinationStageIndex
      : currentStageIndex
  const currentDiagnostic = diagnosticQuestions[activeDiagnostic]
  const currentSource =
    evidenceSources.find((source) => source.id === activeSource) ?? evidenceSources[0]
  const currentVariant = practiceVariants[activeVariant]
  const currentReviewWindow = reviewWindows[activeReviewWindow]

  const moveToStage = useCallback((stageId: StageId) => {
    if (arrivalTimerRef.current !== null) {
      window.clearTimeout(arrivalTimerRef.current)
    }

    setDestinationStage(stageId)
    setStageMoving(true)
    arrivalTimerRef.current = window.setTimeout(() => {
      setActiveStage(stageId)
      setStageMoving(false)
      arrivalTimerRef.current = null
    }, STAGE_TRAVEL_MS)
  }, [])

  useEffect(() => {
    const holdTimer = window.setTimeout(() => {
      const index = learningStages.findIndex((stage) => stage.id === activeStage)
      const nextStage = learningStages[(index + 1) % learningStages.length]
      moveToStage(nextStage.id)
    }, STAGE_HOLD_MS)

    return () => window.clearTimeout(holdTimer)
  }, [activeStage, moveToStage])

  useEffect(() => {
    const diagnosticTimer = window.setTimeout(() => {
      setActiveDiagnostic((current) => (current + 1) % diagnosticQuestions.length)
    }, STAGE_HOLD_MS)

    return () => window.clearTimeout(diagnosticTimer)
  }, [activeDiagnostic])

  useEffect(() => {
    return () => {
      if (arrivalTimerRef.current !== null) {
        window.clearTimeout(arrivalTimerRef.current)
      }
    }
  }, [])

  const openAuth = (mode: AuthMode) => {
    setAuthMode(mode)
    setPasswordVisible(false)
    setAuthError('')
    setAuthNotice('')
    setSubmitting(false)
    setAuthOpen(true)
  }

  const switchAuthMode = (mode: AuthMode) => {
    if (mode === authMode) return
    setAuthMode(mode)
    setPasswordVisible(false)
    setAuthError('')
    setAuthNotice('')
    setSubmitting(false)
  }

  useEffect(() => {
    if (!authOpen) return undefined

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAuthOpen(false)
    }

    document.body.classList.add('auth-dialog-open')
    window.addEventListener('keydown', onKeyDown)

    return () => {
      document.body.classList.remove('auth-dialog-open')
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [authOpen])

  const handlePointerMove = (event: PointerEvent<HTMLElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const x = (event.clientX - rect.left) / rect.width
    const y = (event.clientY - rect.top) / rect.height

    heroRef.current?.style.setProperty('--pointer-x', `${(x - 0.5) * 18}px`)
    heroRef.current?.style.setProperty('--pointer-y', `${(y - 0.5) * 12}px`)
  }

  const resetPointer = () => {
    heroRef.current?.style.setProperty('--pointer-x', '0px')
    heroRef.current?.style.setProperty('--pointer-y', '0px')
  }

  const handleAuth = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    const email = String(formData.get('email') ?? '')
    const password = String(formData.get('password') ?? '')
    const passwordConfirmation = String(formData.get('confirmPassword') ?? '')

    if (
      authMode === 'register' &&
      password !== passwordConfirmation
    ) {
      setAuthError('两次输入的密码不一致，请重新确认。')
      return
    }

    setAuthError('')
    setAuthNotice('')
    setSubmitting(true)

    try {
      if (authMode === 'login') {
        await login({
          email,
          password,
          remember_me: rememberLogin,
        })
        navigate(postLoginPath(location.state), { replace: true })
        return
      }

      await registerWithPassword({
        display_name: String(formData.get('nickname') ?? ''),
        email,
        password,
        password_confirmation: passwordConfirmation,
        accept_terms: true,
        accept_privacy: true,
      })
      setAuthMode('login')
      setPasswordVisible(false)
      setAuthNotice('如果该邮箱可以继续注册，验证邮件已发送。完成邮箱验证后即可登录。')
    } catch (error) {
      setAuthError(authErrorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  const chooseVariant = (index: number) => {
    setActiveVariant(index)
    setSelectedAnswer(null)
  }

  return (
    <main className="login-page">
      <header className="showcase-nav">
        <button
          className="platform-brand"
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          type="button"
        >
          <BrandContent />
        </button>
        <nav aria-label="产品能力">
          <a href="#question">主动追问</a>
          <a href="#evidence">精准诊断</a>
          <a href="#practice">针对训练</a>
          <a href="#review">记忆巩固</a>
        </nav>
        <div className="showcase-nav__actions">
          <button className="showcase-nav__start" onClick={() => openAuth('register')} type="button">
            免费开始
            <ArrowRight size={16} />
          </button>
        </div>
      </header>

      <section
        className="showcase-hero"
        id="home"
        onPointerLeave={resetPointer}
        onPointerMove={handlePointerMove}
        ref={heroRef}
      >
        <svg
          aria-hidden="true"
          className="showcase-hero__coordinates"
          preserveAspectRatio="none"
          viewBox="0 0 1600 860"
        >
          <g>
            <path d="M0 122H1600M0 244H1600M0 366H1600M0 488H1600M0 610H1600M0 732H1600" />
            <path d="M160 0V860M360 0V860M560 0V860M760 0V860M960 0V860M1160 0V860M1360 0V860" />
          </g>
        </svg>

        <div className="showcase-hero__copy">
          <h1>
            408
            <span>学习工作台</span>
          </h1>
          <p className="showcase-hero__statement">
            不只回答一道题，<br />
            而是完成一次学习闭环。
          </p>
          <p className="showcase-hero__lead">
            一个会追问定位、识别知识缺口、安排针对训练并巩固记忆的 408 学习 Agent。
          </p>
          <div className="showcase-hero__actions">
            <a href="#question">
              看四步如何完成
              <ArrowDown size={17} />
            </a>
          </div>
        </div>

        <div
          className={`learning-trace ${stageMoving ? 'is-moving' : ''}`}
          data-active={activeStage}
          data-destination={destinationStage}
        >
          <svg
            aria-hidden="true"
            className="learning-trace__path"
            preserveAspectRatio="none"
            viewBox="0 0 860 580"
          >
            <g className="trace-routes trace-routes--base">
              {routeSegments.map((path) => (
                <path className="trace-route__base" d={path} key={path} />
              ))}
            </g>
            <g className="trace-routes trace-routes--progress">
              {routeSegments.map((path, index) => (
                <path
                  className={`trace-route__progress trace-route__progress--${index + 1} ${index < traceStageIndex ? 'is-reached' : ''}`}
                  d={path}
                  key={path}
                  pathLength="100"
                />
              ))}
            </g>
            <g className="trace-routes trace-routes--signal">
              {routeSegments.map((path, index) => {
                const isGuiding =
                  stageMoving &&
                  destinationStageIndex > currentStageIndex &&
                  index >= currentStageIndex &&
                  index < destinationStageIndex

                return (
                  <path
                    className={`trace-route__signal trace-route__signal--${index + 1} ${isGuiding ? 'is-guiding' : ''}`}
                    d={path}
                    key={path}
                    pathLength="100"
                  />
                )
              })}
            </g>
          </svg>

          {learningStages.map((stage, index) => {
            const Icon = stage.icon
            const isActive = activeStage === stage.id
            const isReached = index <= currentStageIndex
            return (
              <button
                aria-label={`查看第 ${index + 1} 步：${stage.label}`}
                aria-pressed={isActive}
                className={`trace-stage trace-stage--${stage.id} ${isReached ? 'is-reached' : ''} ${isActive ? 'is-active' : ''}`}
                key={stage.id}
                onClick={() => {
                  if (!isActive || stageMoving) moveToStage(stage.id)
                }}
                type="button"
              >
                <span className="trace-stage__node"><Icon size={17} /></span>
                <small>{stage.index}</small>
                <strong>{stage.label}</strong>
              </button>
            )
          })}

          <div className="trace-annotation" data-stage={activeStage} aria-live="polite">
            <header>
              <span><i /> Agent · {currentStage.label}</span>
              <small>{currentStage.meta}</small>
            </header>
            <div className="trace-annotation__copy" key={activeStage}>
              <strong>{currentStage.index}</strong>
              <h2>{currentStage.title}</h2>
              <p>{currentStage.description}</p>
            </div>
            <div className="trace-annotation__steps" aria-hidden="true">
              {learningStages.map((stage, index) => (
                <i className={index <= currentStageIndex ? 'is-reached' : ''} key={stage.id} />
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="capability-section capability-section--question" id="question">
        <div className="capability-section__inner">
          <header className="capability-heading">
            <div className="capability-heading__step">
              <span>01</span>
              <MessageCircleMore size={20} />
            </div>
            <p>Agent 主动追问</p>
            <h2>先一起想清楚，你到底卡在哪里。</h2>
            <span>
              Agent 不把“不会”当成一个结论。它会和你对话，把定义、条件与推导逐一拆开。
            </span>
          </header>

          <div className="dialogue-demo">
            <div
              aria-hidden="true"
              className="dialogue-demo__sketch"
              data-diagnostic={currentDiagnostic.id}
            >
              <svg viewBox="0 0 420 430">
                <image
                  className="thought-person"
                  height="460"
                  href={thoughtProfileUrl}
                  preserveAspectRatio="xMidYMid meet"
                  width="550"
                  x="-70"
                  y="-3"
                />
                <g className="thought-network">
                  <path
                    className="thought-link thought-link--outer"
                    d="M94 84C122 98 155 123 190 139"
                  />
                  <path
                    className="thought-link thought-link--inner"
                    d="M190 139C224 145 258 151 292 158"
                  />
                  <g className="thought-node thought-node--ring">
                    <circle className="thought-node__mask" cx="94" cy="84" r="22" />
                    <circle className="thought-node__halo" cx="94" cy="84" r="25" />
                    <path
                      className="thought-node__shape"
                      d="M76 83C76 71 83 63 94 62C105 62 114 70 114 81C115 93 107 102 96 104C84 105 76 96 76 83Z"
                    />
                  </g>
                  <g className="thought-node thought-node--derive">
                    <circle className="thought-node__mask" cx="190" cy="139" r="22" />
                    <circle className="thought-node__halo" cx="190" cy="139" r="25" />
                    <path
                      className="thought-node__shape"
                      d="M172 138C172 126 179 118 190 117C201 117 210 125 210 136C211 148 203 157 192 159C180 160 172 151 172 138Z"
                    />
                  </g>
                  <g className="thought-node thought-node--convention">
                    <circle className="thought-node__mask" cx="292" cy="158" r="22" />
                    <circle className="thought-node__halo" cx="292" cy="158" r="25" />
                    <path
                      className="thought-node__shape"
                      d="M274 157C274 145 281 137 292 136C303 136 312 144 312 155C313 167 305 176 294 178C282 179 274 170 274 157Z"
                    />
                  </g>
                </g>
              </svg>
            </div>

            <div className="dialogue-demo__thread">
              <ol className="dialogue-sequence">
                <li className="dialogue-step dialogue-step--student">
                  <span className="dialogue-step__marker">01</span>
                  <article className="dialogue-message dialogue-message--student">
                    <header>
                      <span>你</span>
                      <small>提出问题</small>
                    </header>
                    <p>循环队列的 front 公式我总是记不住。</p>
                  </article>
                </li>
                <li className="dialogue-step dialogue-step--agent">
                  <span className="dialogue-step__marker">02</span>
                  <article className="dialogue-message dialogue-message--agent">
                    <header>
                      <span><Sparkles size={14} /> Agent</span>
                      <small>主动追问</small>
                    </header>
                    <p aria-live="polite">{currentDiagnostic.question}</p>
                    <span>先回答这一点，不需要马上写公式。</span>
                    <div className="dialogue-demo__prompts" aria-label="切换 Agent 的追问方向">
                      {diagnosticQuestions.map((item, index) => (
                        <button
                          aria-pressed={activeDiagnostic === index}
                          className={activeDiagnostic === index ? 'is-active' : ''}
                          key={item.id}
                          onClick={() => setActiveDiagnostic(index)}
                          type="button"
                        >
                          <small>{String(index + 1).padStart(2, '0')}</small>
                          <span>{item.short}</span>
                          <ArrowRight aria-hidden="true" size={13} />
                        </button>
                      ))}
                    </div>
                  </article>
                </li>
                <li className="dialogue-step dialogue-step--insight">
                  <span className="dialogue-step__marker">03</span>
                  <article className="dialogue-message dialogue-message--insight">
                    <header>
                      <span><FileCheck2 size={14} /> Agent</span>
                      <small>给出定位</small>
                    </header>
                    <div aria-live="polite">
                      <strong>{currentDiagnostic.result}</strong>
                      <p>{currentDiagnostic.detail}</p>
                    </div>
                  </article>
                </li>
              </ol>
            </div>
          </div>
        </div>
      </section>

      <section className="capability-section capability-section--evidence" id="evidence">
        <div className="capability-section__inner">
          <header className="capability-heading">
            <div className="capability-heading__step">
              <span>02</span>
              <Search size={20} />
            </div>
            <p>知识与题型诊断</p>
            <h2>把一句“不会”，定位成可以训练的具体缺口。</h2>
            <span>
              第一步确认你卡住的位置；这一步再结合知识关系、作答轨迹和同类题表现，追问到足够准确。
            </span>
          </header>

          <div className="evidence-demo" data-source={currentSource.id}>
            <div className="evidence-demo__query">
              <Search size={17} />
              <span>诊断前：只知道“循环队列公式总是记错”</span>
              <small>正在缩小缺口</small>
            </div>

            <div className="evidence-demo__map">
              <svg aria-hidden="true" preserveAspectRatio="none" viewBox="0 0 780 520">
                <path className="evidence-link evidence-link--exam" d="M190 90C345 86 354 187 470 204" />
                <path className="evidence-link evidence-link--knowledge" d="M202 260C340 260 355 244 470 232" />
                <path className="evidence-link evidence-link--outline" d="M220 432C360 410 370 290 470 260" />
              </svg>

              <div className="evidence-demo__sources" aria-label="支持诊断的信号">
                {evidenceSources.map((source) => (
                  <button
                    aria-pressed={activeSource === source.id}
                    className={`evidence-source evidence-source--${source.id} ${activeSource === source.id ? 'is-active' : ''}`}
                    key={source.id}
                    onClick={() => setActiveSource(source.id)}
                    type="button"
                  >
                    <FileCheck2 size={17} />
                    <span>{source.label}</span>
                    <strong>{source.title}</strong>
                    <small>{source.code}</small>
                  </button>
                ))}
              </div>

              <article className="evidence-synthesis" key={currentSource.id}>
                <header>
                  <span>{currentSource.location}</span>
                  <ShieldCheck size={18} />
                </header>
                <blockquote>{currentSource.excerpt}</blockquote>
                <div>
                  <small>诊断后 · 可以开始针对训练</small>
                  <p>
                    你不是记不住整个公式，而是没有识别 rear &lt; front 代表数组发生回绕，
                    因此不会把取模知识迁移到环形下标计算。
                  </p>
                </div>
                <footer>
                  <span><Check size={14} /> 知识缺口：环形下标</span>
                  <span><Check size={14} /> 题型缺口：回绕条件</span>
                </footer>
              </article>
            </div>
          </div>
        </div>
      </section>

      <section className="capability-section capability-section--practice" id="practice">
        <div className="capability-section__inner">
          <header className="capability-heading">
            <div className="capability-heading__step">
              <span>03</span>
              <BookOpenCheck size={20} />
            </div>
            <p>真题 · 模拟 · 复盘</p>
            <h2>围绕已经识别的缺口，完成一轮针对训练。</h2>
            <span>
              先用真题确认考试语境，再用模拟题强化迁移，最后把错误过程整理成可复用的判断方法。
            </span>
          </header>

          <div className="exam-demo">
            <div className="exam-demo__modes">
              <span>训练方式</span>
              <div>
                {practiceVariants.map((variant, index) => (
                  <button
                    className={activeVariant === index ? 'is-active' : ''}
                    key={variant.id}
                    onClick={() => chooseVariant(index)}
                    type="button"
                  >
                    {variant.label}
                  </button>
                ))}
              </div>
              <p>{currentVariant.note}</p>
            </div>

            <article className="exam-sheet" key={currentVariant.id}>
              <header>
                <span>
                  {currentVariant.id === 'trap'
                    ? '本轮训练复盘 · 数据结构'
                    : '408 模拟卷 · 数据结构'}
                </span>
                <small>
                  {currentVariant.id === 'trap' ? (
                    <><Check size={14} /> 已整理</>
                  ) : (
                    <><Clock3 size={14} /> 00:48</>
                  )}
                </small>
              </header>
              <div className="exam-sheet__body">
                <aside className="exam-sheet__number">
                  <small>{currentVariant.id === 'trap' ? '训练总结' : '单项选择题'}</small>
                  <strong>{currentVariant.id === 'trap' ? '01' : '06'}</strong>
                  <span>{currentVariant.id === 'trap' ? '可复用' : '2 分'}</span>
                </aside>
                <div className="exam-sheet__question">
                  {currentVariant.id === 'trap' ? (
                    <div className="exam-sheet__review">
                      <small>这轮训练确认了什么</small>
                      <h3>先识别是否发生回绕，再选择对应的下标关系。</h3>
                      <dl>
                        <div>
                          <dt>识别信号</dt>
                          <dd>rear &lt; front，不代表队列为空，而是数组下标已经回绕。</dd>
                        </div>
                        <div>
                          <dt>判断顺序</dt>
                          <dd>确认指针约定 → 判断是否回绕 → 用容量 m 处理负下标。</dd>
                        </div>
                        <div>
                          <dt>下次提醒</dt>
                          <dd>不要先套公式，先画出 front、rear 与数组边界的位置。</dd>
                        </div>
                      </dl>
                    </div>
                  ) : (
                    <>
                      <h3>{currentVariant.question}</h3>
                      <div className="exam-sheet__options">
                        {currentVariant.options.map((option, index) => {
                          const isSelected = selectedAnswer === index
                          const isCorrect = isSelected && index === currentVariant.correct
                          const isWrong = isSelected && index !== currentVariant.correct
                          return (
                            <button
                              className={`${isSelected ? 'is-selected' : ''} ${isCorrect ? 'is-correct' : ''} ${isWrong ? 'is-wrong' : ''}`}
                              key={option}
                              onClick={() => setSelectedAnswer(index)}
                              type="button"
                            >
                              <span>{String.fromCharCode(65 + index)}</span>
                              <strong>{option}</strong>
                              {isCorrect ? <Check size={16} /> : null}
                            </button>
                          )
                        })}
                      </div>
                    </>
                  )}
                </div>
              </div>
              <footer>
                <span>
                  {currentVariant.id === 'trap'
                    ? '总结已连接到本次错因，后续复习会先要求你主动回忆这套判断顺序。'
                    : selectedAnswer === null
                    ? '作答后，Agent 会把这次结果写入学习轨迹。'
                    : selectedAnswer === currentVariant.correct
                      ? '验证通过：已经能够独立处理环形回绕。'
                      : '仍在机械套用公式，下一题会先改变指针约定。'}
                </span>
                <strong>
                  {currentVariant.id === 'trap'
                    ? '复盘完成'
                    : selectedAnswer === null
                      ? '等待作答'
                      : '已记录'}
                </strong>
              </footer>
            </article>
          </div>
        </div>
      </section>

      <section className="capability-section capability-section--review" id="review">
        <div className="capability-section__inner">
          <header className="capability-heading">
            <div className="capability-heading__step">
              <span>04</span>
              <CalendarCheck2 size={20} />
            </div>
            <p>记忆巩固调度</p>
            <h2>让复习跟随记忆变化，而不是机械重复。</h2>
            <span>
              每次作答都会改变下一次出现的时间。系统根据作答表现估算保持趋势，安排主动回忆，而不是重复浏览。
            </span>
          </header>

          <div className="retention-demo" data-window={currentReviewWindow.id}>
            <header>
              <div>
                <span>循环队列 · 记忆保持轨迹</span>
                <strong>下一窗口：{reviewWindows[1].time}</strong>
              </div>
              <p><i /> 55% 建议复习线</p>
            </header>

            <div className="retention-demo__chart">
              <svg
                aria-label="循环队列未来七天的记忆保持率曲线"
                preserveAspectRatio="none"
                role="img"
                viewBox="0 0 820 360"
              >
                <rect className="retention-zone" height="108" width="820" x="0" y="230" />
                <g className="retention-grid">
                  <line x1="0" x2="820" y1="56" y2="56" />
                  <line x1="0" x2="820" y1="145" y2="145" />
                  <line x1="0" x2="820" y1="230" y2="230" />
                  <line x1="0" x2="820" y1="338" y2="338" />
                  <line x1="292" x2="292" y1="36" y2="338" />
                  <line x1="548" x2="548" y1="36" y2="338" />
                  <line x1="770" x2="770" y1="36" y2="338" />
                </g>
                <line className="retention-threshold" x1="0" x2="820" y1="230" y2="230" />
                <path
                  className="retention-path retention-path--active"
                  d="M45 72C105 128 190 199 292 222L292 70C360 108 452 184 548 205L548 58C620 80 710 130 785 145"
                />
              </svg>
              <span className="retention-axis retention-axis--clear">清晰</span>
              <span className="retention-axis retention-axis--fading">模糊</span>
              <span className="retention-axis retention-axis--critical">临界</span>

              {reviewWindows.map((window, index) => (
                <button
                  aria-pressed={activeReviewWindow === index}
                  className={`retention-node retention-node--${window.id} ${activeReviewWindow === index ? 'is-active' : ''}`}
                  key={window.id}
                  onClick={() => setActiveReviewWindow(index)}
                  style={{
                    left: `${(window.chartX / 820) * 100}%`,
                    top: `${(window.chartY / 360) * 100}%`,
                  }}
                  type="button"
                >
                  <i />
                  <span>
                    <strong>{window.time}</strong>
                    <small>{window.title}</small>
                  </span>
                </button>
              ))}

              <div className="retention-dates" aria-hidden="true">
                <span>今天</span>
                <span>明天</span>
                <span>3 天后</span>
                <span>7 天后</span>
              </div>
            </div>

            <footer className="retention-demo__focus" key={currentReviewWindow.id}>
              <div>
                <strong>{currentReviewWindow.retention}</strong>
                <span>%</span>
                <small>预计保持率</small>
              </div>
              <section>
                <span>{currentReviewWindow.time}</span>
                <h3>{currentReviewWindow.title}</h3>
                <p>{currentReviewWindow.detail}</p>
              </section>
            </footer>
          </div>
        </div>
      </section>

      <footer className="showcase-footer">
        <button
          className="platform-brand platform-brand--footer"
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          type="button"
        >
          <BrandContent />
        </button>
        <p>让每一道不会，都有清楚的下一步。</p>
        <button onClick={() => openAuth('login')} type="button">
          继续学习
          <ArrowRight size={16} />
        </button>
      </footer>

      {authOpen ? (
        <div className="auth-dialog">
          <button
            aria-label="关闭登录窗口"
            className="auth-dialog__backdrop"
            onClick={() => setAuthOpen(false)}
            type="button"
          />
          <aside aria-labelledby="auth-title" aria-modal="true" className="auth-panel" role="dialog">
            <div className="auth-panel__top">
              <div className="platform-brand platform-brand--panel">
                <BrandContent />
              </div>
              <button
                aria-label="关闭"
                className="auth-panel__close"
                onClick={() => setAuthOpen(false)}
                type="button"
              >
                <X size={20} />
              </button>
            </div>

            <div className="auth-mode-switch" aria-label="账户入口">
              <button
                aria-pressed={authMode === 'login'}
                className={authMode === 'login' ? 'is-active' : ''}
                onClick={() => switchAuthMode('login')}
                type="button"
              >
                登录
              </button>
              <button
                aria-pressed={authMode === 'register'}
                className={authMode === 'register' ? 'is-active' : ''}
                onClick={() => switchAuthMode('register')}
                type="button"
              >
                注册
              </button>
            </div>

            <div className="auth-panel__intro">
              <p>{authMode === 'login' ? '账户登录' : '创建账户'}</p>
              <h2 id="auth-title">
                {authMode === 'login' ? '登录后继续学习' : '创建你的学习账户'}
              </h2>
              <span>
                {authMode === 'login'
                  ? '验证账户后，回到今天的问题、训练和复习任务。'
                  : '注册完成后进入短诊断，并生成第一周学习计划。'}
              </span>
            </div>

            <form className="auth-form" key={authMode} onSubmit={handleAuth}>
              {authMode === 'register' ? (
                <label>
                  <span>昵称</span>
                  <div>
                    <UserRound size={18} />
                    <input
                      autoComplete="nickname"
                      autoFocus
                      maxLength={64}
                      name="nickname"
                      placeholder="用于学习工作台"
                      required
                      type="text"
                    />
                  </div>
                </label>
              ) : null}
              <label>
                <span>邮箱</span>
                <div>
                  <Mail size={18} />
                  <input
                    autoComplete="email"
                    autoFocus={authMode === 'login'}
                    maxLength={320}
                    name="email"
                    placeholder="name@example.com"
                    required
                    type="email"
                  />
                </div>
              </label>
              <label>
                <span>密码</span>
                <div>
                  <Lock size={18} />
                  <input
                    autoComplete={authMode === 'login' ? 'current-password' : 'new-password'}
                    maxLength={128}
                    minLength={authMode === 'login' ? 1 : 15}
                    name="password"
                    placeholder={authMode === 'login' ? '输入密码' : '至少 15 位字符'}
                    required
                    type={passwordVisible ? 'text' : 'password'}
                  />
                  <button
                    aria-label={passwordVisible ? '隐藏密码' : '显示密码'}
                    onClick={() => setPasswordVisible((value) => !value)}
                    type="button"
                  >
                    {passwordVisible ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </label>

              {authMode === 'register' ? (
                <label>
                  <span>确认密码</span>
                  <div>
                    <Lock size={18} />
                    <input
                      autoComplete="new-password"
                      maxLength={128}
                      minLength={15}
                      name="confirmPassword"
                      placeholder="再次输入密码"
                      required
                      type={passwordVisible ? 'text' : 'password'}
                    />
                  </div>
                </label>
              ) : null}

              {authMode === 'login' ? (
                <div className="auth-form__options">
                  <label>
                    <input
                      checked={rememberLogin}
                      onChange={(event) => setRememberLogin(event.target.checked)}
                      type="checkbox"
                    />
                    <span>保持登录</span>
                  </label>
                </div>
              ) : (
                <label className="auth-form__consent">
                  <input name="consent" required type="checkbox" />
                  <span>我已阅读并同意服务条款与隐私说明</span>
                </label>
              )}

              {authError ? (
                <p className="auth-form__error" role="alert">
                  <AlertCircle size={15} />
                  {authError}
                </p>
              ) : null}

              {authNotice ? (
                <p className="auth-form__notice" role="status">
                  <Check size={15} />
                  {authNotice}
                </p>
              ) : null}

              <button className="auth-form__submit" disabled={submitting} type="submit">
                {submitting ? (
                  <>
                    <span className="auth-submit-spinner" />
                    {authMode === 'login' ? '正在登录' : '正在创建账户'}
                  </>
                ) : (
                  <>
                    {authMode === 'login' ? '登录并进入工作台' : '注册并开始诊断'}
                    <ArrowRight size={17} />
                  </>
                )}
              </button>
            </form>

            <p className="auth-panel__security">
              <ShieldCheck size={16} />
              学习工作台仅对已登录账户开放
            </p>
          </aside>
        </div>
      ) : null}
    </main>
  )
}

function authErrorMessage(error: unknown): string {
  if (!(error instanceof AuthApiError)) {
    return '认证请求失败，请稍后重试。'
  }
  if (error.code === 'AUTH_RATE_LIMITED' && error.retryAfterSeconds) {
    return `请求过于频繁，请在 ${error.retryAfterSeconds} 秒后重试。`
  }
  if (error.code === 'VALIDATION_ERROR') {
    return '请检查填写内容后重试。'
  }
  return error.message
}
