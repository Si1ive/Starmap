import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Collapse,
  Drawer,
  Empty,
  Space,
  Spin,
  Typography,
  message,
} from 'antd'
import { DatabaseOutlined, HistoryOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import * as agentRunsApi from '@/api/agentRuns'
import type {
  AdminConversationMemory,
  AdminConversationMemorySection,
  AdminConversationMemoryTurn,
  AdminMemorySourceComparison,
} from '@/api/agentRuns'
import PlainDataBlock from './PlainDataBlock'

const { Text, Title } = Typography

interface RunMemoryDrawerProps {
  open: boolean
  threadId: string | null
  onClose: () => void
}

interface SnapshotIndexItem {
  id: number
  source_kind?: string
  source_id?: string | null
  token_estimate?: number
  selected?: boolean
  payload?: unknown
}

const sectionLabels: Record<string, string> = {
  thread_state: '线程热状态',
  snapshot: '本轮上下文快照',
  memory_events: '可信记忆事实',
  memory_items: '长期记忆项',
  mastery: '学习掌握度',
  summaries: '会话摘要',
}

const lookupKinds = new Set([
  'message',
  'current_turn',
  'artifact',
  'conversation_summary',
  'user_learning_mastery',
  'memory_item',
  'preference_candidate',
])

function tokenDelta(value: number) {
  if (!value) return '0'
  return value > 0 ? `+${value}` : String(value)
}

function snapshotItems(value: unknown): SnapshotIndexItem[] {
  if (!value || typeof value !== 'object') return []
  const items = (value as { items?: unknown }).items
  if (!Array.isArray(items)) return []
  return items.filter(
    (item): item is SnapshotIndexItem =>
      Boolean(item) && typeof item === 'object' && typeof (item as SnapshotIndexItem).id === 'number'
  )
}

function MemoryIndexResolver({ runId, value }: { runId: string; value: unknown }) {
  const items = snapshotItems(value).filter(
    (item) => item.source_id && item.source_kind && lookupKinds.has(item.source_kind)
  )
  const [loadingId, setLoadingId] = useState<number | null>(null)
  const [resolved, setResolved] = useState<Record<number, AdminMemorySourceComparison>>({})
  const [errors, setErrors] = useState<Record<number, string>>({})

  if (!items.length) return null

  const resolve = (item: SnapshotIndexItem) => {
    setLoadingId(item.id)
    setErrors((current) => ({ ...current, [item.id]: '' }))
    void agentRunsApi
      .getAgentRunMemorySource(runId, item.id)
      .then((response) => {
        if (response.data) {
          setResolved((current) => ({ ...current, [item.id]: response.data as AdminMemorySourceComparison }))
        }
      })
      .catch(() => {
        setErrors((current) => ({
          ...current,
          [item.id]: '当前数据库记录已删除、版本已变化或不在本 Run 的授权范围内',
        }))
      })
      .finally(() => setLoadingId(null))
  }

  return (
    <div className="memory-index-list">
      <div className="memory-index-list__heading">
        <DatabaseOutlined />
        <strong>索引对应的数据库内容</strong>
        <span>通过 Run + Snapshot Item 绑定回查，不接受任意表名或任意 ID。</span>
      </div>
      {items.map((item) => {
        const comparison = resolved[item.id]
        return (
          <div className="memory-index-item" key={item.id}>
            <div className="memory-index-item__meta">
              <span>{item.source_kind}</span>
              <code>{item.source_id}</code>
              <em>{item.token_estimate || 0} tokens</em>
              <Button loading={loadingId === item.id} onClick={() => resolve(item)} size="small" type="text">
                {comparison ? '重新读取' : '查看真实内容'}
              </Button>
            </div>
            {errors[item.id] ? <p className="memory-index-item__error">{errors[item.id]}</p> : null}
            {comparison ? (
              <div className="memory-index-comparison">
                <div>
                  <span>本轮冻结值 · v{comparison.frozen_version ?? '—'}</span>
                  <PlainDataBlock value={comparison.frozen_copy} maxHeight={240} />
                </div>
                <div>
                  <span>
                    当前数据库值 · v{comparison.current_version ?? '—'}
                    {comparison.superseded ? ' · 已被替代' : ''}
                  </span>
                  <PlainDataBlock value={comparison.current_source} maxHeight={240} />
                </div>
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function MemorySectionPanel({ section, runId }: { section: AdminConversationMemorySection; runId: string }) {
  return (
    <section className={`conversation-memory-panel ${section.changed ? 'is-changed' : 'is-unchanged'}`}>
      <header className="conversation-memory-panel__heading">
        <div>
          <span className="conversation-memory-section__signal" />
          <strong>{sectionLabels[section.key] || section.key}</strong>
          <small>{section.changed ? '本轮内容发生变化' : '本轮内容未变化'}</small>
        </div>
        <em>
          估算 {section.token_before} → {section.token_after} tokens · {tokenDelta(section.token_delta)}
        </em>
      </header>
      <div className="conversation-memory-section__body">
        <div>
          <Text strong>本轮开始前</Text>
          <PlainDataBlock value={section.before} maxHeight={360} />
        </div>
        <div>
          <Text strong>本轮结束后</Text>
          <PlainDataBlock value={section.after} maxHeight={360} />
        </div>
      </div>
      {section.key === 'snapshot' ? <MemoryIndexResolver runId={runId} value={section.after} /> : null}
    </section>
  )
}

function TurnMemoryChange({ turn }: { turn: AdminConversationMemoryTurn }) {
  const [selectedSectionKey, setSelectedSectionKey] = useState<string | null>(null)
  const selectedSection = turn.sections.find((section) => section.key === selectedSectionKey) || null

  return (
    <Collapse
      className={`conversation-memory-turn ${turn.changed ? 'is-changed' : 'is-unchanged'}`}
      items={[
        {
          key: turn.root_run_id,
          label: (
            <div className="conversation-memory-turn__label">
              <span className="conversation-memory-turn__number">第 {turn.turn_number} 轮</span>
              <span className={`conversation-memory-turn__state ${turn.changed ? 'is-changed' : ''}`}>
                {turn.changed ? `${turn.changed_sections.length} 类变化` : '全部未变化'}
              </span>
              <strong>{turn.input_message || '（无文本输入）'}</strong>
              <span className="conversation-memory-turn__tokens">
                {turn.token_totals.before} → {turn.token_totals.after} tokens · {tokenDelta(turn.token_totals.delta)}
              </span>
              <time>{dayjs(turn.observed_at).format('MM-DD HH:mm:ss')}</time>
            </div>
          ),
          children: (
            <div className="conversation-memory-workbench">
              <div className="conversation-memory-total" aria-label="本轮总上下文">
                <div>
                  <span>总上下文</span>
                  <strong>
                    {turn.token_totals.before} → {turn.token_totals.after}
                  </strong>
                  <em>估算 tokens</em>
                </div>
                <div className="conversation-memory-total__delta">
                  <span>{tokenDelta(turn.token_totals.delta)}</span>
                  <small>
                    {turn.changed
                      ? turn.token_totals.delta === 0
                        ? '内容变化 · token 持平'
                        : `${turn.changed_sections.length} 个模块变化`
                      : '内容与 token 均未变化'}
                  </small>
                </div>
              </div>

              <div className="conversation-memory-module-rail" aria-label="上下文记忆模块">
                {turn.sections.map((section) => {
                  const selected = selectedSectionKey === section.key
                  return (
                    <button
                      aria-expanded={selected}
                      className={`conversation-memory-module ${section.changed ? 'is-changed' : 'is-unchanged'} ${selected ? 'is-selected' : ''}`}
                      key={section.key}
                      onClick={() => setSelectedSectionKey(selected ? null : section.key)}
                      type="button"
                    >
                      <span>
                        <i className="conversation-memory-section__signal" />
                        {sectionLabels[section.key] || section.key}
                      </span>
                      <strong>{tokenDelta(section.token_delta)}</strong>
                      <small>
                        {section.token_before} → {section.token_after} tokens
                      </small>
                    </button>
                  )
                })}
              </div>

              {selectedSection ? (
                <MemorySectionPanel runId={turn.root_run_id} section={selectedSection} />
              ) : (
                <div className="conversation-memory-panel-placeholder">
                  选择上方一个记忆模块，查看本轮开始前与结束后的具体上下文。
                </div>
              )}
              {!turn.trace_count ? (
                <Alert
                  description="六个记忆域仍完整展示为沿用状态；这里不把步骤入参、模型输出或派生任务状态算作记忆。"
                  message="本轮没有可用的记忆观测记录"
                  showIcon
                  type="warning"
                />
              ) : null}
            </div>
          ),
        },
      ]}
      size="small"
    />
  )
}

const RunMemoryDrawer = ({ open, threadId, onClose }: RunMemoryDrawerProps) => {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<AdminConversationMemory | null>(null)

  useEffect(() => {
    if (!open || !threadId) return
    setLoading(true)
    setData(null)
    void agentRunsApi
      .getConversationMemory(threadId)
      .then((response) => setData(response.data || null))
      .catch(() => {
        setData(null)
        message.error('会话记忆变化加载失败')
      })
      .finally(() => setLoading(false))
  }, [open, threadId])

  const changedTurns = useMemo(
    () => data?.turns.filter((turn) => turn.changed) || [],
    [data?.turns]
  )

  return (
    <Drawer
      className="memory-observability-drawer conversation-memory-drawer"
      destroyOnClose
      onClose={onClose}
      open={open}
      title="会话上下文记忆变化"
      width="min(1120px, 96vw)"
    >
      {loading ? (
        <div className="admin-page-loading"><Spin size="large" /></div>
      ) : !data ? (
        <Empty description="无法读取该会话的记忆变化" />
      ) : (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <header className="conversation-memory-hero">
            <div>
              <Text type="secondary">{data.thread.id}</Text>
              <Title level={4}>{data.thread.title}</Title>
              <Text>展开一轮后，先核对总上下文，再从横向模块轨道选择要查看的变化。</Text>
            </div>
            <div className="conversation-memory-hero__count" aria-label="记忆变化轮次">
              <HistoryOutlined />
              <strong>{data.changed_turn_count}</strong>
              <span>轮发生变化 / 共 {data.turns.length} 轮</span>
            </div>
          </header>

          <Alert
            description="Snapshot 使用已选入上下文的持久化 token；其余记忆模块使用与 Context Builder 一致的确定性估算。内容变化但 token 总量相同时会明确标记为持平。"
            message="模块内容变化与 token 净增减是两个独立信号"
            showIcon
            type="warning"
          />

          {data.turns.length ? (
            <div className="conversation-memory-timeline">
              {data.turns.map((turn) => <TurnMemoryChange key={turn.root_run_id} turn={turn} />)}
            </div>
          ) : (
            <Empty description="该会话还没有可比较的对话轮次" />
          )}

          {data.turns.length > 0 && changedTurns.length === 0 ? (
            <Alert
              description="可能是会话早于记忆观测功能创建；每轮仍会显示全部域的沿用状态。"
              message="现有历史记录中没有可比较出的变化"
              showIcon
              type="warning"
            />
          ) : null}
        </Space>
      )}
    </Drawer>
  )
}

export default RunMemoryDrawer
