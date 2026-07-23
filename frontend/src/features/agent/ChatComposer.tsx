import { KeyboardEvent, useEffect, useRef } from 'react'
import { LoaderCircle, Send } from 'lucide-react'

interface ChatComposerProps {
  value: string
  disabled?: boolean
  autofocus?: boolean
  focusRequestKey?: number
  onChange: (value: string) => void
  onSubmit: () => void
}

export default function ChatComposer({
  value,
  disabled = false,
  autofocus = false,
  focusRequestKey = 0,
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

  useEffect(() => {
    if (focusRequestKey > 0) textareaRef.current?.focus()
  }, [focusRequestKey])

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
