import { KeyboardEvent, useEffect, useRef } from 'react'
import { Bot, LoaderCircle, RefreshCw, Send } from 'lucide-react'
import type { SelectableAgentModel } from '../../api/agent'

interface ChatComposerProps {
  value: string
  disabled?: boolean
  autofocus?: boolean
  focusRequestKey?: number
  models: SelectableAgentModel[]
  modelsLoading?: boolean
  modelError?: string | null
  selectedModelId: string
  onChange: (value: string) => void
  onModelChange: (modelId: string) => void
  onRetryModels?: () => void
  onSubmit: () => void
}

export default function ChatComposer({
  value,
  disabled = false,
  autofocus = false,
  focusRequestKey = 0,
  models,
  modelsLoading = false,
  modelError = null,
  selectedModelId,
  onChange,
  onModelChange,
  onRetryModels,
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
        <label className="agent-composer__model">
          <Bot aria-hidden="true" size={14} />
          <span className="sr-only">本轮使用的模型</span>
          <select
            aria-label="本轮使用的模型"
            disabled={disabled || modelsLoading || models.length === 0}
            onChange={(event) => onModelChange(event.target.value)}
            value={selectedModelId}
          >
            {modelsLoading ? <option value="">正在加载模型…</option> : null}
            {!modelsLoading && models.length === 0 ? <option value="">暂无可用模型</option> : null}
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.display_name}{model.is_default ? '（默认）' : ''}
              </option>
            ))}
          </select>
        </label>
        {modelError && onRetryModels ? (
          <button
            aria-label="重新加载模型列表"
            className="agent-composer__model-retry"
            disabled={modelsLoading}
            onClick={onRetryModels}
            title="重新加载模型列表"
            type="button"
          >
            <RefreshCw className={modelsLoading ? 'agent-chat-spin' : ''} size={13} />
          </button>
        ) : null}
        <span className="agent-composer__hint">Enter 发送 · Shift + Enter 换行</span>
        <button
          aria-label="发送消息"
          className="agent-composer__send"
          disabled={disabled || modelsLoading || models.length === 0 || !selectedModelId || !value.trim()}
          onClick={onSubmit}
          type="button"
        >
          {disabled ? <LoaderCircle className="agent-chat-spin" size={17} /> : <Send size={17} />}
        </button>
      </div>
      {modelError ? <p className="agent-composer__model-status is-error">{modelError}</p> : null}
      {!modelError && !modelsLoading && models.length === 0 ? (
        <p className="agent-composer__model-status">暂无可用模型，请联系管理员上线模型。</p>
      ) : null}
    </div>
  )
}
