/**
 * Agent 对话页面
 *
 * 连接 backend/app/modules/agent 的 API：
 * - POST /api/v1/agent/threads     创建线程
 * - POST /api/v1/agent/runs        创建运行
 * - GET  /api/v1/agent/runs/{id}   查询运行状态
 * - GET  /api/v1/agent/runs/{id}/events  SSE 事件流
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowRight, BookOpenCheck, Check, ChevronDown, ChevronRight,
  CircleStop, FileCheck2, FileText, History, Lightbulb, ListChecks,
  MessageCircleMore, Paperclip, PanelRightOpen, RefreshCw, RotateCcw,
  Plus, Search, Send, ShieldCheck, Sparkles, TriangleAlert, X, Bot, User,
} from 'lucide-react'
import { Button, Formula, IconButton, PageHeading, SourceBadge, StatusMark } from '../components/Primitives'
import { useAgent } from '../store/agentStore'
import { type AgentEvent } from '../api/agent'

// ==================== Components ====================

function ThreadSidebar({ threads, currentThreadId, onSelect, onNewThread }: {
  threads: { id: string; title: string | null; updated_at: string }[]
  currentThreadId: string | null
  onSelect: (id: string) => void
  onNewThread: () => void
}) {
  return (
    <aside className="thread-sidebar">
      <div className="thread-sidebar__header">
        <PageHeading>对话</PageHeading>
        <Button onClick={onNewThread} variant="primary" size="sm">
          <Plus size={14} /> 新对话
        </Button>
      </div>
      <div className="thread-list">
        {threads.map((t) => (
          <button
            key={t.id}
            className={`thread-item ${t.id === currentThreadId ? 'thread-item--active' : ''}`}
            onClick={() => onSelect(t.id)}
          >
            <MessageCircleMore size={16} />
            <span>{t.title || '新对话'}</span>
          </button>
        ))}
      </div>
    </aside>
  )
}

function EventLog({ events }: { events: AgentEvent[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' }) }, [events])

  return (
    <div ref={ref} className="event-log">
      {events.map((e) => (
        <div key={e.id} className={`event-item event-item--${e.event_type.split('.')[0]}`}>
          <small>#{e.sequence}</small>
          <span className="event-type">{e.event_type}</span>
          <code>{JSON.stringify(e.payload, null, 2)}</code>
        </div>
      ))}
    </div>
  )
}

function RunTrace({ runId, events }: { runId: string; events: AgentEvent[] }) {
  const steps = events.filter(e => e.event_type.startsWith('step.'))
  return (
    <div className="run-trace">
      <div className="run-trace__header">
        <p className="eyebrow">执行轨迹</p>
        <h2>运行 {runId.slice(0, 8)}...</h2>
      </div>
      <div className="trace-list">
        {steps.map((step, i) => (
          <div key={step.id} className={`trace-step trace-step--${step.event_type.split('.')[1] || 'running'}`}>
            <span className="trace-step__line" />
            <span className="trace-step__status">
              {step.event_type === 'step.completed' ? <Check size={14} /> : <Sparkles size={14} />}
            </span>
            <span><small>{String(i + 1).padStart(2, '0')}</small><strong>{step.event_type}</strong></span>
          </div>
        ))}
        {steps.length === 0 && <p className="trace-empty">等待步骤...</p>}
      </div>
    </div>
  )
}

function ChatMessage({ role, content }: { role: 'user' | 'assistant' | 'system'; content: string }) {
  return (
    <div className={`chat-message chat-message--${role}`}>
      <div className="chat-message__avatar">
        {role === 'user' ? <User size={20} /> : <Bot size={20} />}
      </div>
      <div className="chat-message__content">
        <p>{content}</p>
      </div>
    </div>
  )
}

// ==================== Page ====================

function AgentPage() {
  const { threadId } = useParams<{ threadId?: string }>()
  const navigate = useNavigate()
  const {
    state,
    dispatch,
    loadThreads,
    createThread,
    createRun,
    loadRun,
    connectSSE,
    disconnectSSE,
  } = useAgent()

  const [input, setInput] = useState('')
  const [expandedStep, setExpandedStep] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Load threads on mount
  useEffect(() => {
    void loadThreads()
  }, [loadThreads])

  // Auto-focus input
  useEffect(() => {
    inputRef.current?.focus()
  }, [threadId])

  // Handle thread selection
  const handleSelectThread = useCallback((id: string) => {
    navigate(`/agent/${id}`)
  }, [navigate])

  // Handle new thread
  const handleNewThread = useCallback(async () => {
    try {
      const thread = await createThread('新对话')
      navigate(`/agent/${thread.id}`)
    } catch (e) {
      console.error('创建线程失败', e)
    }
  }, [createThread, navigate])

  // Handle send message
  const handleSend = useCallback(async () => {
    if (!input.trim()) return

    const currentThread = state.threads.find((t) => t.id === threadId)
    if (!currentThread && threadId) return

    // If no thread, create one
    let tid = threadId
    if (!tid) {
      try {
        const thread = await createThread()
        tid = thread.id
        navigate(`/agent/${tid}`)
      } catch (e) {
        console.error('创建线程失败', e)
        return
      }
    }

    // Create run
    try {
      const run = await createRun(tid!, 'explain@v1', input.trim())
      dispatch({ type: 'SET_CURRENT_RUN', payload: run.id })
      setInput('')
      // Connect SSE
      connectSSE(run.id)
    } catch (e) {
      console.error('创建运行失败', e)
    }
  }, [input, threadId, state.threads, createThread, navigate, createRun, dispatch, connectSSE])

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => { disconnectSSE() }
  }, [disconnectSSE])

  const currentRun = state.currentRunId ? state.runs[state.currentRunId] : null
  const currentEvents = state.currentRunId ? state.events[state.currentRunId] || [] : []

  return (
    <div className="agent-page">
      <ThreadSidebar
        threads={state.threads.map((t) => ({ id: t.id, title: t.title || '新对话', updated_at: t.updated_at }))}
        currentThreadId={threadId || null}
        onSelect={handleSelectThread}
        onNewThread={handleNewThread}
      />

      <main className="agent-main">
        {/* Messages */}
        <div className="agent-messages">
          {currentEvents.length === 0 && (
            <div className="agent-empty">
              <Sparkles size={32} />
              <h2>开始学习</h2>
              <p>输入你的问题，AI 助手会帮你解答。</p>
            </div>
          )}
          {currentEvents.map((e) => {
            if (e.event_type === 'message.completed') {
              const payload = e.payload as { content?: string }
              return <ChatMessage key={e.id} role="assistant" content={payload.content || ''} />
            }
            return null
          })}
        </div>

        {/* Input */}
        <div className="agent-input">
          <div className="agent-input__box">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="输入你的问题..."
              disabled={state.loading}
            />
            <Button onClick={handleSend} disabled={state.loading || !input.trim()}>
              <Send size={16} />
              {state.loading ? '发送中...' : '发送'}
            </Button>
          </div>
          {state.sseConnected && <span className="sse-indicator">● 实时连接中</span>}
        </div>
      </main>

      {/* Right panel: execution trace */}
      <aside className="agent-trace-panel">
        {currentRun ? (
          <RunTrace runId={currentRun.id} events={currentEvents} />
        ) : (
          <div className="agent-trace-panel__empty">
            <Lightbulb size={24} />
            <p>选择一个运行以查看执行轨迹</p>
          </div>
        )}
      </aside>
    </div>
  )
}

export default AgentPage
