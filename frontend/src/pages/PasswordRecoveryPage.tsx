import { FormEvent, useLayoutEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  Lock,
  Mail,
  ShieldCheck,
} from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AuthApiError, requestPasswordReset, resetPassword } from '../auth'
import PlatformBrand from '../components/PlatformBrand'
import useAuth from '../useAuth'

interface PasswordRecoveryPageProps {
  mode: 'forgot' | 'reset'
}

type ResetState = 'form' | 'complete' | 'invalid'

export default function PasswordRecoveryPage({
  mode,
}: PasswordRecoveryPageProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { restore } = useAuth()
  const [resetToken] = useState(() =>
    mode === 'reset'
      ? (new URLSearchParams(window.location.search).get('token')?.trim() ?? '')
      : '',
  )
  const [emailSent, setEmailSent] = useState(false)
  const [resetState, setResetState] = useState<ResetState>(
    mode === 'reset' && !resetToken ? 'invalid' : 'form',
  )
  const [passwordVisible, setPasswordVisible] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useLayoutEffect(() => {
    if (mode !== 'reset' || !window.location.search) return
    const url = new URL(window.location.href)
    url.searchParams.delete('token')
    const nextUrl = `${url.pathname}${url.search}${url.hash}`
    window.history.replaceState(window.history.state, '', nextUrl)
  }, [mode])

  const copy = useMemo(() => {
    if (mode === 'forgot') {
      return {
        eyebrow: '账户恢复',
        title: emailSent ? '检查你的邮箱' : '找回学习账户',
        description: emailSent
          ? '如果该邮箱对应可恢复的账户，重置链接已经发送。'
          : '输入注册邮箱，我们会发送一条限时、单次使用的重置链接。',
      }
    }
    if (resetState === 'complete') {
      return {
        eyebrow: '密码已更新',
        title: '使用新密码重新登录',
        description: '所有旧会话均已退出。你的学习记录和进度不会受到影响。',
      }
    }
    if (resetState === 'invalid') {
      return {
        eyebrow: '链接不可用',
        title: '重新获取重置邮件',
        description: '当前链接缺失、无效或已经过期，请重新发起密码恢复。',
      }
    }
    return {
      eyebrow: '设置新密码',
      title: '为账户更换密码',
      description: '新密码至少 15 位。完成后需要用新密码重新登录。',
    }
  }, [emailSent, mode, resetState])

  const returnToLogin = () => {
    navigate('/login?auth=login', {
      replace: mode === 'reset',
      state: location.state,
    })
  }

  const handleForgot = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    setError('')
    setSubmitting(true)
    try {
      await requestPasswordReset(String(formData.get('email') ?? ''))
      setEmailSent(true)
    } catch (requestError) {
      setError(recoveryErrorMessage(requestError))
    } finally {
      setSubmitting(false)
    }
  }

  const handleReset = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    const password = String(formData.get('password') ?? '')
    const confirmation = String(formData.get('passwordConfirmation') ?? '')
    if (password !== confirmation) {
      setError('两次输入的密码不一致，请重新确认。')
      return
    }

    setError('')
    setSubmitting(true)
    try {
      await resetPassword({
        token: resetToken,
        password,
        password_confirmation: confirmation,
      })
      setResetState('complete')
      void restore()
    } catch (requestError) {
      if (
        requestError instanceof AuthApiError &&
        requestError.code === 'PASSWORD_RESET_INVALID'
      ) {
        setResetState('invalid')
      } else {
        setError(recoveryErrorMessage(requestError))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="recovery-page">
      <header className="recovery-header">
        <button
          className="platform-brand recovery-brand"
          onClick={returnToLogin}
          type="button"
        >
          <PlatformBrand />
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
          <p>ACCOUNT SECURITY / 账户安全</p>
          <h1>{copy.title}</h1>
          <span>{copy.description}</span>
          <div className="recovery-context__assurances">
            <div>
              <ShieldCheck size={18} />
              <span>
                <strong>链接只可使用一次</strong>
                <small>重发后旧链接会立即失效</small>
              </span>
            </div>
            <div>
              <Lock size={18} />
              <span>
                <strong>重置后撤销旧会话</strong>
                <small>其他设备需要使用新密码登录</small>
              </span>
            </div>
          </div>
        </div>

        <div className="recovery-panel">
          <div className="recovery-panel__heading">
            <p>{copy.eyebrow}</p>
            <h2>{copy.title}</h2>
            <span>{copy.description}</span>
          </div>

          {mode === 'forgot' ? (
            emailSent ? (
              <RecoveryComplete
                actionLabel="返回登录"
                description="没有收到邮件时，请检查垃圾邮件，或等待片刻后重新提交。"
                onAction={returnToLogin}
                onSecondary={() => {
                  setEmailSent(false)
                  setError('')
                }}
                secondaryLabel="重新填写邮箱"
              />
            ) : (
              <form className="recovery-form" onSubmit={handleForgot}>
                <label>
                  <span>注册邮箱</span>
                  <div>
                    <Mail size={18} />
                    <input
                      autoComplete="email"
                      autoCapitalize="none"
                      autoFocus
                      inputMode="email"
                      maxLength={320}
                      name="email"
                      placeholder="name@example.com"
                      required
                      spellCheck={false}
                      type="text"
                    />
                  </div>
                </label>
                <RecoveryError message={error} />
                <button
                  className="recovery-form__submit"
                  disabled={submitting}
                  type="submit"
                >
                  {submitting ? <span className="auth-submit-spinner" /> : null}
                  {submitting ? '正在发送' : '发送重置邮件'}
                  {!submitting ? <ArrowRight size={17} /> : null}
                </button>
                <p className="recovery-form__privacy">
                  无论邮箱是否注册，页面都会显示相同结果。
                </p>
              </form>
            )
          ) : resetState === 'complete' ? (
            <RecoveryComplete
              actionLabel="使用新密码登录"
              description="密码变更通知已发送到你的账户邮箱。"
              onAction={returnToLogin}
            />
          ) : resetState === 'invalid' ? (
            <RecoveryComplete
              actionLabel="重新获取重置邮件"
              description="为保护账户，失效链接不能再次使用。"
              onAction={() => navigate('/forgot-password', { replace: true })}
              tone="warning"
            />
          ) : (
            <form className="recovery-form" onSubmit={handleReset}>
              <PasswordField
                autoFocus
                label="新密码"
                name="password"
                passwordVisible={passwordVisible}
                placeholder="至少 15 位字符"
                toggleVisibility={() => setPasswordVisible((value) => !value)}
              />
              <PasswordField
                label="确认新密码"
                name="passwordConfirmation"
                passwordVisible={passwordVisible}
                placeholder="再次输入新密码"
              />
              <RecoveryError message={error} />
              <button
                className="recovery-form__submit"
                disabled={submitting}
                type="submit"
              >
                {submitting ? <span className="auth-submit-spinner" /> : null}
                {submitting ? '正在更新密码' : '更新密码并退出旧会话'}
                {!submitting ? <ArrowRight size={17} /> : null}
              </button>
            </form>
          )}
        </div>
      </section>
    </main>
  )
}

function PasswordField({
  autoFocus = false,
  label,
  name,
  passwordVisible,
  placeholder,
  toggleVisibility,
}: {
  autoFocus?: boolean
  label: string
  name: string
  passwordVisible: boolean
  placeholder: string
  toggleVisibility?: () => void
}) {
  return (
    <label>
      <span>{label}</span>
      <div>
        <Lock size={18} />
        <input
          autoComplete="new-password"
          autoFocus={autoFocus}
          maxLength={128}
          minLength={15}
          name={name}
          placeholder={placeholder}
          required
          type={passwordVisible ? 'text' : 'password'}
        />
        {toggleVisibility ? (
          <button
            aria-label={passwordVisible ? '隐藏密码' : '显示密码'}
            onClick={toggleVisibility}
            type="button"
          >
            {passwordVisible ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        ) : null}
      </div>
    </label>
  )
}

function RecoveryError({ message }: { message: string }) {
  return message ? (
    <p className="recovery-form__error" role="alert">
      <AlertCircle size={16} />
      {message}
    </p>
  ) : null
}

function RecoveryComplete({
  actionLabel,
  description,
  onAction,
  onSecondary,
  secondaryLabel,
  tone = 'success',
}: {
  actionLabel: string
  description: string
  onAction: () => void
  onSecondary?: () => void
  secondaryLabel?: string
  tone?: 'success' | 'warning'
}) {
  return (
    <div className={`recovery-result recovery-result--${tone}`}>
      <span className="recovery-result__icon">
        {tone === 'success' ? <Check size={24} /> : <AlertCircle size={24} />}
      </span>
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
          className="recovery-result__secondary"
          onClick={onSecondary}
          type="button"
        >
          {secondaryLabel}
        </button>
      ) : null}
    </div>
  )
}

function recoveryErrorMessage(error: unknown): string {
  if (!(error instanceof AuthApiError)) {
    return '账户恢复请求失败，请稍后重试。'
  }
  if (error.code === 'AUTH_RATE_LIMITED' && error.retryAfterSeconds) {
    return `请求过于频繁，请在 ${error.retryAfterSeconds} 秒后重试。`
  }
  if (error.code === 'VALIDATION_ERROR') {
    return '请检查填写内容后重试。'
  }
  return error.message
}
