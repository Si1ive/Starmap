import {
  ClipboardEvent,
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  Clock3,
  Link2,
  MailCheck,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  AuthApiError,
  EmailVerificationCredential,
  resendEmailVerification,
} from '../auth'
import useAuth from '../useAuth'

type VerificationPhase = 'code' | 'confirming' | 'complete' | 'invalid'

interface VerificationRouteState {
  from?: unknown
  verificationEmail?: unknown
  resendAfterSeconds?: unknown
}

const CODE_LENGTH = 6
const DEFAULT_RESEND_SECONDS = 60

export default function EmailVerificationPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { verifyEmail } = useAuth()
  const routeState = (location.state ?? null) as VerificationRouteState | null
  const email =
    typeof routeState?.verificationEmail === 'string'
      ? routeState.verificationEmail
      : ''
  const initialResendSeconds = useMemo(
    () => boundedResendSeconds(routeState?.resendAfterSeconds),
    [routeState?.resendAfterSeconds],
  )
  const [verificationToken] = useState(
    () =>
      new URLSearchParams(window.location.search).get('token')?.trim() ?? '',
  )
  const [phase, setPhase] = useState<VerificationPhase>(
    verificationToken ? 'confirming' : 'code',
  )
  const [digits, setDigits] = useState(() =>
    Array.from({ length: CODE_LENGTH }, () => ''),
  )
  const [countdown, setCountdown] = useState(initialResendSeconds)
  const [submitting, setSubmitting] = useState(false)
  const [resending, setResending] = useState(false)
  const [error, setError] = useState('')
  const [resendNotice, setResendNotice] = useState('')
  const inputsRef = useRef<Array<HTMLInputElement | null>>([])
  const autoConfirmationStarted = useRef(false)

  useLayoutEffect(() => {
    if (!window.location.search) return
    const url = new URL(window.location.href)
    url.searchParams.delete('token')
    const nextUrl = `${url.pathname}${url.search}${url.hash}`
    window.history.replaceState(window.history.state, '', nextUrl)
  }, [])

  useEffect(() => {
    if (countdown <= 0) return undefined
    const timer = window.setInterval(() => {
      setCountdown((current) => Math.max(0, current - 1))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [countdown])

  const finishVerification = useCallback(
    async (credential: EmailVerificationCredential, fromLink = false) => {
      setError('')
      setResendNotice('')
      setSubmitting(true)
      if (fromLink) setPhase('confirming')
      try {
        const result = await verifyEmail(credential)
        if (result.authenticated) {
          navigate('/onboarding', { replace: true })
          return
        }
        setPhase('complete')
      } catch (verificationError) {
        if (
          verificationError instanceof AuthApiError &&
          verificationError.code === 'VERIFICATION_INVALID'
        ) {
          if (fromLink) {
            setPhase('invalid')
          } else {
            setDigits(Array.from({ length: CODE_LENGTH }, () => ''))
            setError('验证码无效、已过期或尝试次数过多，请检查后重试。')
            window.setTimeout(() => inputsRef.current[0]?.focus(), 0)
          }
        } else {
          setError(verificationErrorMessage(verificationError))
        }
      } finally {
        setSubmitting(false)
      }
    },
    [navigate, verifyEmail],
  )

  useEffect(() => {
    if (!verificationToken || autoConfirmationStarted.current) return
    autoConfirmationStarted.current = true
    void finishVerification({ token: verificationToken }, true)
  }, [finishVerification, verificationToken])

  const submitCode = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const code = digits.join('')
    if (code.length !== CODE_LENGTH) {
      setError('请输入邮件中的 6 位数字验证码。')
      inputsRef.current[digits.findIndex((digit) => !digit)]?.focus()
      return
    }
    void finishVerification({ code })
  }

  const updateDigit = (index: number, value: string) => {
    const numeric = value.replace(/\D/g, '')
    if (!numeric) {
      setDigits((current) =>
        current.map((digit, digitIndex) => (digitIndex === index ? '' : digit)),
      )
      return
    }
    applyCode(index, numeric)
  }

  const applyCode = (startIndex: number, value: string) => {
    const next = [...digits]
    const incoming = value.slice(0, CODE_LENGTH - startIndex).split('')
    incoming.forEach((digit, offset) => {
      next[startIndex + offset] = digit
    })
    setDigits(next)
    setError('')
    const nextIndex = Math.min(startIndex + incoming.length, CODE_LENGTH - 1)
    window.setTimeout(() => inputsRef.current[nextIndex]?.focus(), 0)
  }

  const handleCodeKeyDown = (
    event: KeyboardEvent<HTMLInputElement>,
    index: number,
  ) => {
    if (event.key === 'Backspace' && !digits[index] && index > 0) {
      inputsRef.current[index - 1]?.focus()
    }
    if (event.key === 'ArrowLeft' && index > 0) {
      event.preventDefault()
      inputsRef.current[index - 1]?.focus()
    }
    if (event.key === 'ArrowRight' && index < CODE_LENGTH - 1) {
      event.preventDefault()
      inputsRef.current[index + 1]?.focus()
    }
  }

  const handlePaste = (
    event: ClipboardEvent<HTMLInputElement>,
    index: number,
  ) => {
    const numeric = event.clipboardData.getData('text').replace(/\D/g, '')
    if (!numeric) return
    event.preventDefault()
    applyCode(index, numeric)
  }

  const resend = async () => {
    if (countdown > 0 || resending) return
    setError('')
    setResendNotice('')
    setResending(true)
    try {
      const result = await resendEmailVerification()
      setCountdown(boundedResendSeconds(result.resend_after_seconds))
      setResendNotice(
        '如果注册事务仍有效，新的验证邮件已经发出，旧凭据会被替换。',
      )
    } catch (resendError) {
      if (
        resendError instanceof AuthApiError &&
        resendError.code === 'AUTH_RATE_LIMITED' &&
        resendError.retryAfterSeconds
      ) {
        setCountdown(resendError.retryAfterSeconds)
      }
      setError(verificationErrorMessage(resendError))
    } finally {
      setResending(false)
    }
  }

  const returnToLogin = () => {
    const from =
      phase === 'complete'
        ? { pathname: '/onboarding', search: '', hash: '' }
        : routeState?.from
    navigate('/login?auth=login', {
      replace: phase === 'complete',
      state: { from },
    })
  }

  const editEmail = () => {
    navigate('/login?auth=register', {
      state: {
        from: routeState?.from,
        registrationEmail: email,
      },
    })
  }

  const copy = verificationCopy(phase)

  return (
    <main className="recovery-page verification-page">
      <header className="recovery-header">
        <button
          className="recovery-brand"
          onClick={returnToLogin}
          type="button"
        >
          <span aria-hidden="true">
            <MailCheck size={20} />
          </span>
          <strong>408 学习工作台</strong>
        </button>
        <button
          className="recovery-header__return"
          onClick={returnToLogin}
          type="button"
        >
          <ArrowLeft size={17} />
          返回登录
        </button>
      </header>

      <section className="recovery-workspace">
        <div className="recovery-context">
          <p>EMAIL OWNERSHIP / 邮箱验证</p>
          <h1>
            {copy.contextTitleParts.map((part) => (
              <span key={part}>{part}</span>
            ))}
          </h1>
          <span>{copy.contextDescription}</span>
          <div className="recovery-context__assurances">
            <div>
              <Link2 size={18} />
              <span>
                <strong>链接与数字码属于同一事务</strong>
                <small>任一方式验证成功，另一种方式立即失效</small>
              </span>
            </div>
            <div>
              <ShieldCheck size={18} />
              <span>
                <strong>数字码绑定当前注册浏览器</strong>
                <small>不能仅凭邮箱和 6 位数字登录账户</small>
              </span>
            </div>
          </div>
        </div>

        <div className="recovery-panel verification-panel">
          <div className="recovery-panel__heading">
            <p>{copy.eyebrow}</p>
            <h2>{copy.title}</h2>
            <span>{copy.description}</span>
          </div>

          {phase === 'confirming' ? (
            <VerificationProgress error={error} onReturn={returnToLogin} />
          ) : phase === 'complete' ? (
            <VerificationResult
              description="邮箱已经验证。当前浏览器没有原注册事务，请重新登录后继续。"
              onAction={returnToLogin}
              title="验证完成"
            />
          ) : phase === 'invalid' ? (
            <VerificationResult
              actionLabel="改用 6 位验证码"
              description="链接可能已过期、已使用，或被新邮件替换。原注册浏览器仍可输入最新邮件中的数字码。"
              onAction={() => {
                setError('')
                setPhase('code')
                window.setTimeout(() => inputsRef.current[0]?.focus(), 0)
              }}
              onSecondary={editEmail}
              secondaryLabel="重新填写注册邮箱"
              title="验证链接不可用"
              warning
            />
          ) : (
            <form className="verification-form" onSubmit={submitCode}>
              {email ? (
                <p className="verification-email-target">
                  验证邮件已发送至 <strong>{email}</strong>
                </p>
              ) : (
                <p className="verification-email-target">
                  输入最新验证邮件中的数字码。
                </p>
              )}

              <fieldset className="verification-code">
                <legend>6 位数字验证码</legend>
                <div className="verification-code__inputs">
                  {digits.map((digit, index) => (
                    <input
                      aria-label={`验证码第 ${index + 1} 位`}
                      autoComplete={index === 0 ? 'one-time-code' : 'off'}
                      autoFocus={index === 0}
                      inputMode="numeric"
                      key={index}
                      maxLength={1}
                      onChange={(event) =>
                        updateDigit(index, event.target.value)
                      }
                      onFocus={(event) => event.currentTarget.select()}
                      onKeyDown={(event) => handleCodeKeyDown(event, index)}
                      onPaste={(event) => handlePaste(event, index)}
                      pattern="[0-9]*"
                      ref={(element) => {
                        inputsRef.current[index] = element
                      }}
                      value={digit}
                    />
                  ))}
                </div>
              </fieldset>

              {error ? (
                <p className="recovery-form__error" role="alert">
                  <AlertCircle size={16} />
                  {error}
                </p>
              ) : null}
              {resendNotice ? (
                <p className="verification-form__notice" role="status">
                  <Check size={16} />
                  {resendNotice}
                </p>
              ) : null}

              <button
                className="recovery-form__submit"
                disabled={submitting}
                type="submit"
              >
                {submitting ? <span className="auth-submit-spinner" /> : null}
                {submitting ? '正在验证' : '验证邮箱并继续'}
                {!submitting ? <ArrowRight size={17} /> : null}
              </button>

              <div className="verification-form__secondary">
                <button
                  disabled={countdown > 0 || resending}
                  onClick={() => void resend()}
                  type="button"
                >
                  {resending ? (
                    <RefreshCw className="spin" size={15} />
                  ) : (
                    <Clock3 size={15} />
                  )}
                  {resending
                    ? '正在重新发送'
                    : countdown > 0
                      ? `${countdown} 秒后可重新发送`
                      : '重新发送验证邮件'}
                </button>
                <button onClick={editEmail} type="button">
                  修改邮箱
                </button>
              </div>
            </form>
          )}
        </div>
      </section>
    </main>
  )
}

function VerificationProgress({
  error,
  onReturn,
}: {
  error: string
  onReturn: () => void
}) {
  return (
    <div className="verification-progress" role={error ? 'alert' : 'status'}>
      {error ? (
        <>
          <span className="verification-progress__icon is-warning">
            <AlertCircle size={25} />
          </span>
          <p>{error}</p>
          <button
            className="recovery-form__submit"
            onClick={onReturn}
            type="button"
          >
            返回登录
            <ArrowRight size={17} />
          </button>
        </>
      ) : (
        <>
          <span className="verification-progress__spinner" />
          <strong>正在安全地消费单次验证凭据</strong>
          <p>验证完成后会自动进入下一步。</p>
        </>
      )}
    </div>
  )
}

function VerificationResult({
  actionLabel = '重新登录并继续',
  description,
  onAction,
  onSecondary,
  secondaryLabel,
  title,
  warning = false,
}: {
  actionLabel?: string
  description: string
  onAction: () => void
  onSecondary?: () => void
  secondaryLabel?: string
  title: string
  warning?: boolean
}) {
  return (
    <div
      className={`verification-result ${warning ? 'is-warning' : ''}`}
      role="status"
    >
      <span className="verification-result__icon">
        {warning ? <AlertCircle size={25} /> : <Check size={25} />}
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
      <button
        className="recovery-form__submit"
        onClick={onAction}
        type="button"
      >
        {actionLabel}
        <ArrowRight size={17} />
      </button>
      {onSecondary && secondaryLabel ? (
        <button
          className="verification-result__secondary"
          onClick={onSecondary}
          type="button"
        >
          {secondaryLabel}
        </button>
      ) : null}
    </div>
  )
}

function verificationCopy(phase: VerificationPhase) {
  if (phase === 'confirming') {
    return {
      eyebrow: '正在验证',
      title: '确认邮件链接',
      description: '正在检查这条限时、单次使用的验证凭据。',
      contextTitleParts: ['确认邮箱', '控制权'],
      contextDescription:
        '验证只激活当前注册账户，不会把数字码作为长期登录凭据。',
    }
  }
  if (phase === 'complete') {
    return {
      eyebrow: '邮箱已验证',
      title: '账户已经激活',
      description: '重新登录后即可开始首次学习设置。',
      contextTitleParts: ['邮箱验证', '完成'],
      contextDescription:
        '当前链接不在原注册浏览器中打开，因此需要正常登录后继续。',
    }
  }
  if (phase === 'invalid') {
    return {
      eyebrow: '链接不可用',
      title: '换一种验证方式',
      description: '你可以回到原注册浏览器输入最新邮件中的 6 位数字码。',
      contextTitleParts: ['这条链接', '无法继续'],
      contextDescription:
        '重发邮件会立即替换旧链接；已经使用或过期的凭据也不能再次消费。',
    }
  }
  return {
    eyebrow: '等待验证',
    title: '输入邮件中的数字码',
    description: '验证码为 6 位数字，只能在发起注册的浏览器中使用。',
    contextTitleParts: ['还差一次', '邮箱确认'],
    contextDescription:
      '完成验证后，原注册浏览器会直接建立正式会话并进入首次学习设置。',
  }
}

function boundedResendSeconds(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.min(3600, Math.max(1, Math.ceil(value)))
    : DEFAULT_RESEND_SECONDS
}

function verificationErrorMessage(error: unknown): string {
  if (!(error instanceof AuthApiError)) {
    return '邮箱验证请求失败，请稍后重试。'
  }
  if (error.code === 'AUTH_RATE_LIMITED' && error.retryAfterSeconds) {
    return `请求过于频繁，请在 ${error.retryAfterSeconds} 秒后重试。`
  }
  if (error.code === 'VALIDATION_ERROR') {
    return '验证凭据格式不正确，请检查后重试。'
  }
  return error.message
}
