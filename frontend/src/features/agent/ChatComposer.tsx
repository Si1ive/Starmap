import { KeyboardEvent, useEffect, useRef } from 'react'
import { LoaderCircle, Send } from 'lucide-react'

export type AgentActionPreference = 'auto' | 'explain' | 'validate' | 'grade' | 'plan'

interface ChatComposerProps {
  value: string
  action: AgentActionPreference
  disabled?: boolean
  autofocus?: boolean
  onActionChange: (action: AgentActionPreference) => void
  onChange: (value: string) => void
  onSubmit: () => void
}

export default function ChatComposer({
  value,
  action,
  disabled = false,
  autofocus = false,
  onActionChange,
  onChange,
  onSubmit,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = '0px'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`
  }, [value])

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    onSubmit()
  }

  return (
    <div className="agent-composer">
      <textarea
        aria-label="发送消息"
        autoFocus={autofocus}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="给 Agent 发消息…"
        ref={textareaRef}
        rows={1}
        value={value}
      />
      <div className="agent-composer__footer">
        <label className="agent-composer__mode">
          <span className="sr-only">处理方式</span>
          <select
            disabled={disabled}
            onChange={(event) => onActionChange(event.target.value as AgentActionPreference)}
            value={action}
          >
            <option value="auto">自动处理</option>
            <option value="explain">讲解</option>
            <option value="validate">验证理解</option>
            <option value="grade">批改反馈</option>
            <option value="plan">调整计划</option>
          </select>
        </label>
        <span className="agent-composer__hint">Enter 发送 · Shift + Enter 换行</span>
        <button
          aria-label="发送消息"
          className="agent-composer__send"
          disabled={disabled || !value.trim()}
          onClick={onSubmit}
          type="button"
        >
          {disabled ? <LoaderCircle className="agent-chat-spin" size={17} /> : <Send size={17} />}
        </button>
      </div>
    </div>
  )
}
