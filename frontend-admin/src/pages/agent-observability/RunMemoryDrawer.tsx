import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
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
            <p className="admin-eyebrow">Memory flight recorder</p>
            <span>Run 记忆观测</span>
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
