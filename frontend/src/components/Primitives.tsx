import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { ArrowRight, Check, ChevronRight, Info, LoaderCircle, X } from 'lucide-react'
import { InlineMath } from 'react-katex'

type ButtonTone = 'primary' | 'secondary' | 'quiet' | 'danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: ButtonTone
  icon?: ReactNode
}

export function Button({
  tone = 'primary',
  icon,
  className = '',
  children,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button className={`button button--${tone} ${className}`} type={type} {...props}>
      {icon}
      <span>{children}</span>
    </button>
  )
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string
  children: ReactNode
}

export function IconButton({ label, children, className = '', ...props }: IconButtonProps) {
  return (
    <button
      aria-label={label}
      className={`icon-button ${className}`}
      title={label}
      type="button"
      {...props}
    >
      {children}
    </button>
  )
}

export function PageHeading({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <header className="page-heading">
      <div>
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        {description ? <p className="page-heading__description">{description}</p> : null}
      </div>
      {actions ? <div className="page-heading__actions">{actions}</div> : null}
    </header>
  )
}

export function SectionHeading({
  title,
  meta,
  action,
}: {
  title: string
  meta?: string
  action?: ReactNode
}) {
  return (
    <div className="section-heading">
      <div>
        <h2>{title}</h2>
        {meta ? <p>{meta}</p> : null}
      </div>
      {action}
    </div>
  )
}

const sourceTone: Record<string, string> = {
  outline: 'source--outline',
  question: 'source--question',
  knowledge: 'source--knowledge',
  personal: 'source--personal',
  generated: 'source--generated',
  inference: 'source--inference',
}

export function SourceBadge({ type, children }: { type: string; children: ReactNode }) {
  return <span className={`source-badge ${sourceTone[type] ?? ''}`}>{children}</span>
}

export function StatusMark({
  tone,
  children,
}: {
  tone: 'success' | 'running' | 'warning' | 'error' | 'neutral'
  children: ReactNode
}) {
  const icon =
    tone === 'success' ? (
      <Check size={13} />
    ) : tone === 'running' ? (
      <LoaderCircle className="spin" size={13} />
    ) : tone === 'error' ? (
      <X size={13} />
    ) : tone === 'warning' ? (
      <Info size={13} />
    ) : null

  return (
    <span className={`status-mark status-mark--${tone}`}>
      {icon}
      {children}
    </span>
  )
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  return (
    <div className="progress" aria-label={label} aria-valuemax={100} aria-valuemin={0} aria-valuenow={value}>
      <span style={{ width: `${value}%` }} />
    </div>
  )
}

export function Formula({ children }: { children: string }) {
  return (
    <span className="formula">
      <InlineMath math={children} />
    </span>
  )
}

export function InlineLink({
  children,
  onClick,
}: {
  children: ReactNode
  onClick?: () => void
}) {
  return (
    <button className="inline-link" onClick={onClick} type="button">
      {children}
      <ChevronRight size={14} />
    </button>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action: ReactNode
}) {
  return (
    <div className="empty-state">
      <div className="empty-state__mark">
        <span />
        <span />
        <span />
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  )
}

export function NextAction({
  label,
  description,
  onClick,
}: {
  label: string
  description: string
  onClick: () => void
}) {
  return (
    <button className="next-action" onClick={onClick} type="button">
      <span>
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
      <ArrowRight size={18} />
    </button>
  )
}
