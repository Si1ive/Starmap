import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Drawer,
  Empty,
  Modal,
  Row,
  Segmented,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  ApartmentOutlined,
  DatabaseOutlined,
  EyeOutlined,
  FileSearchOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'

import * as agentRunsApi from '@/api/agentRuns'
import type {
  AdminMemoryTrace,
  AdminRuntimeContextTrace,
  AdminMemorySnapshotItem,
  AdminMemorySourceComparison,
  AdminRunMemoryObservability,
  AdminRunMemoryReplay,
} from '@/api/agentRuns'
import PlainDataBlock from './PlainDataBlock'

const { Text, Title } = Typography

interface RunMemoryDrawerProps {
  open: boolean
  runId: string | null
  onClose: () => void
}

const selectionColor = (selected: boolean) => (selected ? 'success' : 'warning')

const memoryTraceLabels: Record<string, string> = {
  'run.created': '运行创建',
  'run.status_changed': '运行状态变化',
  'run.completed': '运行完成',
  'run.failed': '运行失败',
  'step.started': '步骤开始',
  'step.completed': '步骤完成',
  'step.failed': '步骤失败',
  'tool.called': '工具调用',
  'tool.result': '工具返回',
  'artifact.rendered': '产物落库',
}

const memoryTraceLabel = (eventType: string) => {
  if (memoryTraceLabels[eventType]) return memoryTraceLabels[eventType]
  if (eventType.startsWith('memory.outbox.')) {
    return eventType.endsWith('.failed') ? '记忆投影失败' : '记忆投影完成'
  }
  return eventType
}

const SnapshotItemCard = ({
  item,
  onInspectSource,
}: {
  item: AdminMemorySnapshotItem
  onInspectSource: (item: AdminMemorySnapshotItem) => void
}) => (
  <Card className={`memory-item-card ${item.selected ? 'is-selected' : 'is-dropped'}`} size="small">
    <div className="memory-item-card__head">
      <Space wrap size={6}>
        <Tag color={selectionColor(item.selected)}>{item.selected ? '已选择' : '已丢弃'}</Tag>
        <Text strong>{item.memory_partition}</Text>
        <Tag bordered={false}>{item.memory_need}</Tag>
      </Space>
      <Text className="memory-mono" type="secondary">
        {item.token_estimate} tokens
      </Text>
    </div>
    <div className="memory-item-card__source">
      <span>{item.source_kind}</span>
      <code>{item.source_id || '无 source ID'}</code>
      <span>v{item.version ?? '—'}</span>
    </div>
    <Text type={item.selected ? undefined : 'warning'}>
      {item.selected
        ? item.selection_reason || '命中选择策略'
        : item.dropped_reason || '未进入本轮上下文'}
    </Text>
    {item.source_lookup_supported ? (
      <Button icon={<EyeOutlined />} onClick={() => onInspectSource(item)} size="small" type="link">
        对比当前 source
      </Button>
    ) : (
      <Text type="secondary">该类型不支持在线 source 回查；可在只读复现中查看冻结副本。</Text>
    )}
  </Card>
)

function MemoryTraceCard({ trace }: { trace: AdminMemoryTrace }) {
  return (
    <Collapse
      className={`memory-trace-entry ${trace.changed ? 'is-changed' : 'is-unchanged'}`}
      items={[
        {
          key: String(trace.id),
          label: (
            <Space wrap size={8}>
              <Tag color={trace.changed ? 'processing' : 'default'}>
                {trace.changed ? '发生变化' : '前后无变化'}
              </Tag>
              <Text strong>{memoryTraceLabel(trace.event_type)}</Text>
              <Text className="memory-mono" type="secondary">
                {trace.event_type}
              </Text>
              {trace.event_sequence !== null ? (
                <Text type="secondary">事件 #{trace.event_sequence}</Text>
              ) : null}
              <Text type="secondary">
                {dayjs(trace.created_at).format('MM-DD HH:mm:ss')}
              </Text>
            </Space>
          ),
          children: trace.changed ? (
            <Row gutter={[12, 12]}>
              <Col xs={24} md={12}>
                <Text strong>事件前</Text>
                <PlainDataBlock value={trace.before} maxHeight={240} />
              </Col>
              <Col xs={24} md={12}>
                <Text strong>事件后</Text>
                <PlainDataBlock value={trace.after} maxHeight={240} />
              </Col>
            </Row>
          ) : (
            <Text type="secondary">
              该事件没有改变线程热状态、Snapshot、长期记忆、掌握度或派生任务。
            </Text>
          ),
        },
      ]}
      size="small"
    />
  )
}

function RuntimeContextCard({ trace }: { trace: AdminRuntimeContextTrace }) {
  const changed = trace.changed_keys.length > 0
  return (
    <Collapse
      items={[{
        key: trace.step_id,
        label: (
          <Space wrap size={8}>
            <Tag color={changed ? 'processing' : 'default'}>
              {changed ? `${trace.changed_keys.length} 个 key 变化` : '无相邻上下文变化'}
            </Tag>
            <Text strong>{trace.node_name}</Text>
            {trace.added_keys.map((key) => <Tag color="green" key={key}>+ {key}</Tag>)}
          </Space>
        ),
        children: (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text type="secondary">
              这里展示工作流临时上下文；检索焦点、候选章节和 RAG 证据不会因此成为长期记忆。
            </Text>
            <Row gutter={[12, 12]}>
              <Col xs={24} lg={8}><Text strong>步骤前上下文</Text><PlainDataBlock value={trace.before} maxHeight={260} /></Col>
              <Col xs={24} lg={8}><Text strong>步骤输出</Text><PlainDataBlock value={trace.output} maxHeight={260} /></Col>
              <Col xs={24} lg={8}><Text strong>下一步骤输入</Text><PlainDataBlock value={trace.next_step_before || {}} maxHeight={260} /></Col>
            </Row>
          </Space>
        ),
      }]}
      size="small"
    />
  )
}

const RunMemoryDrawer = ({ open, runId, onClose }: RunMemoryDrawerProps) => {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<AdminRunMemoryObservability | null>(null)
  const [selectionView, setSelectionView] = useState<'all' | 'selected' | 'dropped'>('all')
  const [source, setSource] = useState<AdminMemorySourceComparison | null>(null)
  const [sourceLoading, setSourceLoading] = useState(false)
  const [replay, setReplay] = useState<AdminRunMemoryReplay | null>(null)
  const [replayLoading, setReplayLoading] = useState(false)

  useEffect(() => {
    if (!open || !runId) return
    setLoading(true)
    setData(null)
    setReplay(null)
    setSource(null)
    void agentRunsApi
      .getAgentRunMemory(runId)
      .then((response) => setData(response.data || null))
      .catch(() => {
        setData(null)
        message.error('Run 记忆观测数据加载失败')
      })
      .finally(() => setLoading(false))
  }, [open, runId])

  const visibleItems = useMemo(() => {
    const items = data?.items || []
    if (selectionView === 'selected') return items.filter((item) => item.selected)
    if (selectionView === 'dropped') return items.filter((item) => !item.selected)
    return items
  }, [data?.items, selectionView])

  const selectedCount = data?.items.filter((item) => item.selected).length || 0
  const droppedCount = (data?.items.length || 0) - selectedCount

  const inspectSource = async (item: AdminMemorySnapshotItem) => {
    if (!runId) return
    setSourceLoading(true)
    try {
      const response = await agentRunsApi.getAgentRunMemorySource(runId, item.id)
      setSource(response.data || null)
    } catch {
      setSource(null)
      message.error('当前 source 不存在、已删除或不再匹配冻结版本')
    } finally {
      setSourceLoading(false)
    }
  }

  const loadReplay = async () => {
    if (!runId) return
    setReplayLoading(true)
    try {
      const response = await agentRunsApi.replayAgentRunMemory(runId)
      setReplay(response.data || null)
    } catch {
      message.error('Snapshot 复现失败')
    } finally {
      setReplayLoading(false)
    }
  }

  return (
    <>
      <Drawer
        className="memory-observability-drawer"
        destroyOnClose
        onClose={onClose}
        open={open}
        title={
          <div>
            <p className="admin-eyebrow">Run context &amp; persistent memory</p>
            <span>Run 上下文与记忆观测</span>
          </div>
        }
        width="min(980px, 96vw)"
      >
        {loading ? (
          <div className="admin-page-loading">
            <Spin size="large" />
          </div>
        ) : !data ? (
          <Empty description="无法读取该 Run 的记忆观测数据" />
        ) : (
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <div className="memory-trace" aria-label="Run 到派生任务的记忆轨迹">
              <div className="memory-trace__node is-run">
                <ApartmentOutlined />
                <span>RUN</span>
                <code>{data.run.id}</code>
              </div>
              <span className="memory-trace__line" />
              <div className={`memory-trace__node ${data.snapshot ? 'is-snapshot' : 'is-muted'}`}>
                <DatabaseOutlined />
                <span>SNAPSHOT</span>
                <code>{data.snapshot?.id || '未冻结'}</code>
              </div>
              <span className="memory-trace__line" />
              <div className="memory-trace__node is-outbox">
                <HistoryOutlined />
                <span>OUTBOX</span>
                <code>{data.memory_outbox.length} tasks</code>
              </div>
            </div>

            {!data.snapshot ? (
              <Alert
                description="该 Run 没有绑定可复现 Snapshot；不会回退到当前在线记忆重新推导。"
                message="没有冻结快照"
                showIcon
                type="warning"
              />
            ) : null}

            <Row gutter={[12, 12]}>
              <Col xs={24} md={14}>
                <Card className="memory-summary-card" size="small" title="当时如何理解这一轮">
                  <Descriptions column={1} size="small">
                    <Descriptions.Item label="原始输入">
                      <Text>{data.run.raw_input || '—'}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="独立请求">
                      <Text>{data.snapshot?.standalone_request || '—'}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="Snapshot">
                      <Text className="memory-mono" copyable={Boolean(data.snapshot?.id)}>
                        {data.snapshot?.id || '—'}
                      </Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="冻结时间">
                      {data.snapshot?.created_at
                        ? dayjs(data.snapshot.created_at).format('YYYY-MM-DD HH:mm:ss')
                        : '—'}
                    </Descriptions.Item>
                    <Descriptions.Item label="状态版本">
                      <Text className="memory-mono">v{data.snapshot?.state_version ?? '—'}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="MemoryNeed">
                      <Space wrap>
                        {data.snapshot?.memory_needs.map((need) => (
                          <Tag key={need}>{need}</Tag>
                        ))}
                      </Space>
                    </Descriptions.Item>
                  </Descriptions>
                  <PlainDataBlock value={data.turn_understanding} maxHeight={220} />
                  <Text strong>选择元数据</Text>
                  <PlainDataBlock value={data.snapshot?.selection_metadata} maxHeight={160} />
                </Card>
              </Col>
              <Col xs={24} md={10}>
                <Card className="memory-summary-card" size="small" title="本轮预算与调用">
                  <div className="memory-ledger">
                    <div>
                      <span>上下文预算</span>
                      <strong>{data.token_budget.configured ?? '—'}</strong>
                    </div>
                    <div>
                      <span>上下文估算</span>
                      <strong>{data.token_budget.context_estimated ?? '—'}</strong>
                    </div>
                    <div>
                      <span>选中 Token</span>
                      <strong>{data.token_budget.selected_items}</strong>
                    </div>
                    <div>
                      <span>丢弃 Token</span>
                      <strong>{data.token_budget.dropped_items}</strong>
                    </div>
                  </div>
                  <Descriptions column={1} size="small">
                    <Descriptions.Item label="模型">{data.model.name || '—'}</Descriptions.Item>
                    <Descriptions.Item label="最后调用 ID">
                      <Text
                        className="memory-mono"
                        copyable={Boolean(data.model.final_model_call_id)}
                      >
                        {data.model.final_model_call_id || '—'}
                      </Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="调用预算">
                      {data.model.model_call_count} / {data.model.max_model_calls}
                    </Descriptions.Item>
                  </Descriptions>
                  <Button
                    block
                    disabled={!data.snapshot}
                    icon={<FileSearchOutlined />}
                    loading={replayLoading}
                    onClick={() => void loadReplay()}
                  >
                    只读复现 Snapshot
                  </Button>
                </Card>
              </Col>
            </Row>

            <section aria-labelledby="memory-selection-title">
              <div className="memory-section-heading">
                <div>
                  <p className="admin-eyebrow">Selection ledger</p>
                  <Title id="memory-selection-title" level={5}>
                    记忆选择账本
                  </Title>
                </div>
                <Segmented
                  onChange={(value) => setSelectionView(value as typeof selectionView)}
                  options={[
                    { label: `全部 ${data.items.length}`, value: 'all' },
                    { label: `已选 ${selectedCount}`, value: 'selected' },
                    { label: `丢弃 ${droppedCount}`, value: 'dropped' },
                  ]}
                  value={selectionView}
                />
              </div>
              {visibleItems.length ? (
                <div className="memory-item-grid">
                  {visibleItems.map((item) => (
                    <SnapshotItemCard item={item} key={item.id} onInspectSource={inspectSource} />
                  ))}
                </div>
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="没有符合条件的 Snapshot Item"
                />
              )}
            </section>

            <section aria-labelledby="runtime-context-title">
              <div className="memory-section-heading">
                <div>
                  <p className="admin-eyebrow">Ephemeral execution state</p>
                  <Title id="runtime-context-title" level={5}>运行上下文轨迹</Title>
                </div>
                <Text type="secondary">{data.runtime_context_trace.length} 个工作流步骤</Text>
              </div>
              <Alert
                message="运行上下文与持久化 Memory 分开观测"
                description="关键词、大纲命中、RAG 证据和节点中间结果属于本次 Run 的临时上下文；下方持久化记忆无变化并不表示工作流上下文没有变化。"
                showIcon
                type="info"
                style={{ marginBottom: 12 }}
              />
              {data.runtime_context_trace.length ? (
                <div className="memory-trace-list">
                  {data.runtime_context_trace.map((trace) => <RuntimeContextCard key={trace.step_id} trace={trace} />)}
                </div>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该 Run 没有可用的步骤上下文快照" />
              )}
            </section>

            <section aria-labelledby="memory-trace-title">
              <div className="memory-section-heading">
                <div>
                  <p className="admin-eyebrow">Before / after</p>
                  <Title id="memory-trace-title" level={5}>
                    持久化记忆变化时间线
                  </Title>
                </div>
                <Text type="secondary">
                  {data.memory_trace?.length || 0} 个关键边界；message.delta 不重复记录
                </Text>
              </div>
              {data.memory_trace?.length ? (
                <div className="memory-trace-list">
                  {data.memory_trace.map((trace) => (
                    <MemoryTraceCard key={trace.id} trace={trace} />
                  ))}
                </div>
              ) : (
                <Alert
                  message="该 Run 尚未产生持久化记忆前后观测"
                  description="旧 Run 可能是在记忆观测上线前执行；新 Run 会在工作流关键事件和 Memory Outbox 投影边界记录前后状态。"
                  showIcon
                  type="info"
                />
              )}
            </section>

            <Row gutter={[12, 12]}>
              <Col xs={24} lg={12}>
                <Card size="small" title={`实际工具调用（${data.tool_calls.length}）`}>
                  <PlainDataBlock value={data.tool_calls} maxHeight={280} />
                </Card>
              </Col>
              <Col xs={24} lg={12}>
                <Card size="small" title={`派生任务（${data.memory_outbox.length}）`}>
                  {data.memory_outbox.some((row) => row.safe_error_summary) ? (
                    <Alert
                      message="派生任务包含安全错误摘要"
                      showIcon
                      type="warning"
                      style={{ marginBottom: 10 }}
                    />
                  ) : null}
                  <PlainDataBlock value={data.memory_outbox} maxHeight={280} />
                </Card>
              </Col>
            </Row>
            <Card size="small" title={`模型调用审计（${data.model.calls.length}）`}>
              <PlainDataBlock value={data.model.calls} maxHeight={280} />
            </Card>
          </Space>
        )}
      </Drawer>

      <Modal
        footer={null}
        onCancel={() => setSource(null)}
        open={Boolean(source) || sourceLoading}
        title="冻结副本 / 当前 source"
        width="min(920px, 94vw)"
      >
        {sourceLoading ? (
          <div className="admin-page-loading">
            <Spin />
          </div>
        ) : source ? (
          <>
            <Space wrap style={{ marginBottom: 12 }}>
              <Tag>{source.source_kind}</Tag>
              <Text className="memory-mono">{source.source_id || '—'}</Text>
              <Tag color={source.superseded ? 'warning' : 'success'}>
                {source.superseded ? '当前 source 已被替代' : '当前 source 仍有效'}
              </Tag>
              <Text type="secondary">
                冻结 v{source.frozen_version ?? '—'} / 当前 v{source.current_version ?? '—'}
              </Text>
            </Space>
            <Alert
              message="左侧是旧 Run 实际消费的冻结副本；右侧当前 source 仅用于对照，不参与复现。"
              showIcon
              type="info"
              style={{ marginBottom: 12 }}
            />
            <Row gutter={[12, 12]}>
              <Col xs={24} md={12}>
                <Text strong>冻结副本</Text>
                <PlainDataBlock value={source.frozen_copy} />
              </Col>
              <Col xs={24} md={12}>
                <Text strong>当前 source</Text>
                <PlainDataBlock value={source.current_source} />
              </Col>
            </Row>
          </>
        ) : null}
      </Modal>

      <Modal
        footer={null}
        onCancel={() => setReplay(null)}
        open={Boolean(replay)}
        title="Snapshot 只读复现"
        width="min(980px, 94vw)"
      >
        {replay ? (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Alert
              message="本视图只重组冻结事实，没有重新调用模型、检索工具或当前 source。"
              showIcon
              type="success"
            />
            <Descriptions column={2} size="small">
              <Descriptions.Item label="模式">{replay.mode}</Descriptions.Item>
              <Descriptions.Item label="Snapshot">{replay.snapshot.id}</Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {dayjs(replay.snapshot.created_at).format('YYYY-MM-DD HH:mm:ss')}
              </Descriptions.Item>
              <Descriptions.Item label="Item 数">{replay.ordered_items.length}</Descriptions.Item>
            </Descriptions>
            <PlainDataBlock
              maxHeight={520}
              value={{
                turn_understanding: replay.turn_understanding,
                ordered_items: replay.ordered_items,
                token_budget: replay.token_budget,
                actual_tool_calls: replay.actual_tool_calls,
              }}
            />
          </Space>
        ) : null}
      </Modal>
    </>
  )
}

export default RunMemoryDrawer
