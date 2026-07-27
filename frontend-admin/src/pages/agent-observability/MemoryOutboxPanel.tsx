import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { EyeOutlined, ReloadOutlined, RetweetOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'

import * as agentRunsApi from '@/api/agentRuns'
import type { AdminMemoryOutbox, MemoryOutboxParams } from '@/api/agentRuns'
import PlainDataBlock from './PlainDataBlock'

const { RangePicker } = DatePicker
const { Text } = Typography

const outboxStatus: Record<string, { label: string; color: string }> = {
  pending: { label: '等待处理', color: 'gold' },
  processing: { label: '处理中', color: 'blue' },
  completed: { label: '已完成', color: 'green' },
  failed: { label: '失败', color: 'red' },
}

const MemoryOutboxPanel = () => {
  const [rows, setRows] = useState<AdminMemoryOutbox[]>([])
  const [loading, setLoading] = useState(false)
  const [replayingId, setReplayingId] = useState<number | null>(null)
  const [detail, setDetail] = useState<AdminMemoryOutbox | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [filters, setFilters] = useState<MemoryOutboxParams>({})
  const [draft, setDraft] = useState<MemoryOutboxParams>({})
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })

  const fetchRows = useCallback(
    async (page = 1, pageSize = 20) => {
      setLoading(true)
      try {
        const response = await agentRunsApi.getMemoryOutbox({
          ...filters,
          page,
          page_size: pageSize,
        })
        setRows(response.data?.items || [])
        setPagination({
          current: page,
          pageSize,
          total: response.data?.total || 0,
        })
      } catch {
        setRows([])
      } finally {
        setLoading(false)
      }
    },
    [filters]
  )

  useEffect(() => {
    void fetchRows(1, 20)
  }, [fetchRows])

  const inspect = async (outboxId: number) => {
    setDetailLoading(true)
    setDetail(null)
    try {
      const response = await agentRunsApi.getMemoryOutboxDetail(outboxId)
      setDetail(response.data || null)
    } catch {
      message.error('Memory Outbox 详情加载失败')
    } finally {
      setDetailLoading(false)
    }
  }

  const replay = async (row: AdminMemoryOutbox) => {
    setReplayingId(row.id)
    try {
      const response = await agentRunsApi.replayMemoryOutbox(row.id)
      message.success(`Outbox #${response.data?.id || row.id} 已恢复为等待处理`)
      await fetchRows(pagination.current, pagination.pageSize)
      if (detail?.id === row.id) setDetail(response.data || null)
    } catch {
      message.error('Outbox 重放失败；任务状态可能已变化，请刷新后重试')
    } finally {
      setReplayingId(null)
    }
  }

  const columns: ColumnsType<AdminMemoryOutbox> = [
    {
      title: '任务',
      key: 'task',
      width: 250,
      render: (_, row) => (
        <Space direction="vertical" size={1}>
          <Space size={6}>
            <Text className="memory-mono" strong>
              #{row.id}
            </Text>
            <Text strong>{row.event_type}</Text>
          </Space>
          <Text className="memory-mono" copyable type="secondary">
            {row.task_key || row.run_id || '无 Run 治理任务'}
          </Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (status: string) => (
        <Tag color={outboxStatus[status]?.color || 'default'}>
          {outboxStatus[status]?.label || status}
        </Tag>
      ),
    },
    {
      title: '作用域',
      key: 'scope',
      width: 210,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Text className="memory-mono" type="secondary">
            thread · {row.thread_id}
          </Text>
          <Text className="memory-mono" type="secondary">
            user · {row.user_id}
          </Text>
        </Space>
      ),
    },
    {
      title: '重试',
      dataIndex: 'retry_count',
      key: 'retry_count',
      align: 'center',
      width: 76,
    },
    {
      title: '最后安全错误',
      dataIndex: 'safe_error_summary',
      key: 'safe_error_summary',
      width: 300,
      ellipsis: true,
      render: (value: string | null, row) =>
        value ? (
          <Text type={row.status === 'failed' ? 'danger' : 'secondary'}>{value}</Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '计划 / 完成',
      key: 'time',
      width: 180,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Text>{dayjs(row.scheduled_at).format('MM-DD HH:mm:ss')}</Text>
          <Text type="secondary">
            {row.processed_at ? dayjs(row.processed_at).format('MM-DD HH:mm:ss') : '尚未完成'}
          </Text>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      fixed: 'right',
      width: 156,
      render: (_, row) => (
        <Space size={2}>
          <Button
            icon={<EyeOutlined />}
            onClick={() => void inspect(row.id)}
            size="small"
            type="link"
          >
            详情
          </Button>
          <Popconfirm
            cancelText="取消"
            description="只恢复原任务的调度状态，不会强制写入派生记忆。"
            disabled={!row.replay_allowed}
            okText="重放原任务"
            onConfirm={() => void replay(row)}
            title="确认重放这个 Outbox？"
          >
            <Button
              disabled={!row.replay_allowed}
              icon={<RetweetOutlined />}
              loading={replayingId === row.id}
              size="small"
              title={row.replay_block_reason || undefined}
              type="link"
            >
              重放
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="memory-outbox-panel">
      <div className="memory-outbox-intro">
        <div>
          <p className="admin-eyebrow">Derived memory queue</p>
          <Typography.Title level={4}>Memory Outbox</Typography.Title>
          <Typography.Paragraph type="secondary">
            查看派生记忆的真实处理状态、最后安全错误，并沿用原幂等身份重新排队。
          </Typography.Paragraph>
        </div>
        <div className="memory-outbox-intro__rule">
          <RetweetOutlined />
          <span>重放只恢复原任务</span>
          <small>不克隆 · 不强制成功 · 不跳过版本校验</small>
        </div>
      </div>

      <Card className="memory-filter-card" size="small">
        <div className="memory-filter-grid">
          <Input
            allowClear
            onChange={(event) =>
              setDraft((value) => ({ ...value, event_type: event.target.value || undefined }))
            }
            placeholder="Event type"
            value={draft.event_type}
          />
          <Select
            allowClear
            onChange={(status) => setDraft((value) => ({ ...value, status }))}
            options={Object.entries(outboxStatus).map(([value, config]) => ({
              value,
              label: config.label,
            }))}
            placeholder="处理状态"
            value={draft.status}
          />
          <Input
            allowClear
            onChange={(event) =>
              setDraft((value) => ({ ...value, run_id: event.target.value || undefined }))
            }
            placeholder="Run ID"
            value={draft.run_id}
          />
          <Input
            allowClear
            onChange={(event) =>
              setDraft((value) => ({ ...value, thread_id: event.target.value || undefined }))
            }
            placeholder="Thread ID"
            value={draft.thread_id}
          />
          <Input
            allowClear
            onChange={(event) =>
              setDraft((value) => ({ ...value, source_id: event.target.value || undefined }))
            }
            placeholder="Source ID"
            value={draft.source_id}
          />
          <RangePicker
            onChange={(dates) =>
              setDraft((value) => ({
                ...value,
                start_date: dates?.[0]?.toISOString(),
                end_date: dates?.[1]?.toISOString(),
              }))
            }
            showTime
          />
          <Button icon={<SearchOutlined />} onClick={() => setFilters({ ...draft })} type="primary">
            应用筛选
          </Button>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => void fetchRows(pagination.current, pagination.pageSize)}
          >
            刷新
          </Button>
        </div>
      </Card>

      <Card className="memory-outbox-table-card" size="small">
        <Table
          columns={columns}
          dataSource={rows}
          loading={loading}
          locale={{ emptyText: <Empty description="当前筛选下没有 Memory Outbox" /> }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: pagination.total,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 个派生任务`,
            onChange: (page, pageSize) => void fetchRows(page, pageSize),
          }}
          rowClassName={(row) => (row.status === 'failed' ? 'memory-outbox-row--failed' : '')}
          rowKey="id"
          scroll={{ x: 1300 }}
          size="middle"
        />
      </Card>

      <Drawer
        className="memory-observability-drawer"
        onClose={() => setDetail(null)}
        open={Boolean(detail) || detailLoading}
        title="Memory Outbox 详情"
        width="min(760px, 96vw)"
      >
        {detailLoading ? (
          <div className="admin-page-loading">
            <Spin size="large" />
          </div>
        ) : detail ? (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {detail.safe_error_summary ? (
              <Alert
                description={detail.safe_error_summary}
                message="最后安全错误"
                showIcon
                type={detail.status === 'failed' ? 'error' : 'warning'}
              />
            ) : null}
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="Outbox ID">#{detail.id}</Descriptions.Item>
              <Descriptions.Item label="Event type">{detail.event_type}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={outboxStatus[detail.status]?.color}>
                  {outboxStatus[detail.status]?.label}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Run / Task key">
                <Text className="memory-mono">{detail.task_key || detail.run_id || '—'}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="Thread">
                <Text className="memory-mono">{detail.thread_id}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="重试次数">{detail.retry_count}</Descriptions.Item>
              <Descriptions.Item label="Worker">{detail.worker_id || '—'}</Descriptions.Item>
              <Descriptions.Item label="重放资格">
                {detail.replay_allowed ? (
                  <Tag color="success">允许</Tag>
                ) : (
                  <Tag>{detail.replay_block_reason}</Tag>
                )}
              </Descriptions.Item>
            </Descriptions>
            <div>
              <Text strong>脱敏载荷</Text>
              <PlainDataBlock value={detail.payload} maxHeight={380} />
            </div>
            <Popconfirm
              cancelText="取消"
              description="消费者仍会重新校验 user、thread、source 与版本。"
              disabled={!detail.replay_allowed}
              okText="重放原任务"
              onConfirm={() => void replay(detail)}
              title="确认恢复为等待处理？"
            >
              <Button
                block
                disabled={!detail.replay_allowed}
                icon={<RetweetOutlined />}
                loading={replayingId === detail.id}
                type="primary"
              >
                重放原 Outbox
              </Button>
            </Popconfirm>
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}

export default MemoryOutboxPanel
