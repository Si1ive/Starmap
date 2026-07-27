import { useState } from 'react'
import {
  Card, Table, Tag, Space, Input, Select, Row, Col, Statistic, Button, Drawer, Descriptions,
  Alert, Popconfirm, message, DatePicker,
} from 'antd'
import { type Dayjs } from 'dayjs'
import {
  ReloadOutlined, DeleteOutlined, CompressOutlined, EyeOutlined,
  WarningOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getServiceLogs, getServiceLogStats, deleteServiceLogs, archiveServiceLogs,
  type ServiceLogItem,
} from '@/api'

const { Search } = Input
const { RangePicker } = DatePicker

const levelColor: Record<string, string> = {
  CRITICAL: '#a8071a',
  ERROR: '#ff4d4f',
  WARNING: '#fa8c16',
  INFO: '#1890ff',
  DEBUG: '#666',
}

const MonitorErrors = () => {
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [filters, setFilters] = useState<{ level?: string; logger_name?: string; keyword?: string; request_id?: string }>({ level: 'ERROR' })
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [statsHours, setStatsHours] = useState(24)
  const [detail, setDetail] = useState<ServiceLogItem | null>(null)

  const params = {
    page, page_size: pageSize, ...filters,
    start_time: dateRange?.[0]?.toISOString(),
    end_time: dateRange?.[1]?.toISOString(),
  }

  const { data: logsRes, refetch, isLoading } = useQuery({
    queryKey: ['serviceLogs', params],
    queryFn: () => getServiceLogs(params),
  })

  const { data: statsRes } = useQuery({
    queryKey: ['serviceLogStats', statsHours],
    queryFn: () => getServiceLogStats(statsHours),
    refetchInterval: 60000,
  })

  const cleanMut = useMutation({
    mutationFn: (older_than_days: number) => deleteServiceLogs({ older_than_days }),
    onSuccess: (res) => {
      message.success(`已清理 ${res.data?.deleted ?? 0} 条`)
      qc.invalidateQueries({ queryKey: ['serviceLogs'] })
      qc.invalidateQueries({ queryKey: ['serviceLogStats'] })
    },
    onError: () => message.error('清理失败'),
  })

  const archiveMut = useMutation({
    mutationFn: (older_than_days: number) => archiveServiceLogs(older_than_days),
    onSuccess: (res) => {
      const data = res.data
      message.success(`已归档 ${data?.archived ?? 0} 条到 ${data?.path ?? ''}`)
      qc.invalidateQueries({ queryKey: ['serviceLogs'] })
    },
    onError: () => message.error('归档失败'),
  })

  const list = logsRes?.data
  const stats = statsRes?.data

  const totalByLevel = (lvl: string) => stats?.by_level.find((x) => x.level === lvl)?.count ?? 0

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '-',
    },
    {
      title: '级别',
      dataIndex: 'level',
      width: 100,
      render: (l: string) => <Tag color={levelColor[l] || 'default'}>{l}</Tag>,
    },
    {
      title: 'Logger',
      dataIndex: 'logger_name',
      width: 200,
      ellipsis: true,
      render: (v: string) => <span style={{ fontFamily: 'monospace', color: '#666' }}>{v || '-'}</span>,
    },
    {
      title: '消息',
      dataIndex: 'message',
      ellipsis: true,
    },
    {
      title: 'Request ID',
      dataIndex: 'request_id',
      width: 180,
      ellipsis: true,
      render: (v: string) => v ? <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{v}</span> : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 70,
      render: (_: unknown, r: ServiceLogItem) => (
        <Button type="link" icon={<EyeOutlined />} size="small" onClick={() => setDetail(r)}>详情</Button>
      ),
    },
  ]

  return (
    <div>
      {stats?.sink_health && (stats.sink_health.dropped_count > 0 || stats.sink_health.flush_failures > 0) && (
        <Alert
          showIcon
          type="warning"
          message={`日志 Sink 异常：丢弃 ${stats.sink_health.dropped_count} 条，写入失败 ${stats.sink_health.flush_failures} 次`}
          description={`当前队列 ${stats.sink_health.queue_size}/${stats.sink_health.queue_capacity}；队列满时保留最新日志。`}
          style={{ marginBottom: 16 }}
        />
      )}
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>服务日志</h2>
        <Space>
          <Select
            value={statsHours}
            style={{ width: 130 }}
            onChange={setStatsHours}
            options={[
              { label: '近 1 小时', value: 1 },
              { label: '近 24 小时', value: 24 },
              { label: '近 7 天', value: 24 * 7 },
              { label: '近 30 天', value: 24 * 30 },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => refetch()}>刷新</Button>
          <Popconfirm
            title="清理 7 天前的所有日志？"
            onConfirm={() => cleanMut.mutate(7)}
          >
            <Button danger icon={<DeleteOutlined />} loading={cleanMut.isPending}>清理 7 天前</Button>
          </Popconfirm>
          <Popconfirm
            title="把 30 天前的日志归档为 .ndjson.gz 后清库？"
            onConfirm={() => archiveMut.mutate(30)}
          >
            <Button icon={<CompressOutlined />} loading={archiveMut.isPending}>归档 30 天前</Button>
          </Popconfirm>
        </Space>
      </div>

      {/* 级别统计 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="ERROR" value={totalByLevel('ERROR')} valueStyle={{ color: levelColor.ERROR }}
              prefix={<WarningOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="WARNING" value={totalByLevel('WARNING')} valueStyle={{ color: levelColor.WARNING }}
              prefix={<ExclamationCircleOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="INFO" value={totalByLevel('INFO')} valueStyle={{ color: levelColor.INFO }} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="近 24h 总数" value={stats?.by_level.reduce((s, x) => s + x.count, 0) ?? 0} />
          </Card>
        </Col>
      </Row>

      {/* Top loggers */}
      {stats?.top_loggers && stats.top_loggers.length > 0 && (
        <Card size="small" title="Top 10 Logger（按日志量）" style={{ marginBottom: 16 }}>
          <Space wrap>
            {stats.top_loggers.map((l) => (
              <Tag key={l.logger} color="geekblue" onClick={() => setFilters({ ...filters, logger_name: l.logger })} style={{ cursor: 'pointer' }}>
                {l.logger}: {l.count}
              </Tag>
            ))}
          </Space>
        </Card>
      )}

      <Card
        size="small"
        title="日志明细"
        extra={
          <Space wrap>
            <Select
              value={filters.level}
              allowClear
              placeholder="级别"
              style={{ width: 120 }}
              onChange={(v) => setFilters({ ...filters, level: v })}
              options={['ERROR', 'WARNING', 'INFO', 'DEBUG'].map((x) => ({ label: x, value: x }))}
            />
            <Input
              placeholder="logger 名称"
              allowClear
              style={{ width: 200 }}
              onChange={(e) => setFilters({ ...filters, logger_name: e.target.value || undefined })}
            />
            <Input
              placeholder="Request ID"
              allowClear
              style={{ width: 200 }}
              onChange={(e) => setFilters({ ...filters, request_id: e.target.value || undefined })}
            />
            <Search
              placeholder="搜索消息"
              allowClear
              style={{ width: 200 }}
              onSearch={(v) => setFilters({ ...filters, keyword: v || undefined })}
            />
            <RangePicker showTime onChange={(v) => setDateRange(v as any)} />
          </Space>
        }
      >
        <Table
          loading={isLoading}
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={list?.items || []}
          pagination={{
            current: page,
            pageSize,
            total: list?.total || 0,
            showSizeChanger: true,
            onChange: (p, s) => { setPage(p); setPageSize(s) },
          }}
        />
      </Card>

      <Drawer title="日志详情" open={!!detail} onClose={() => setDetail(null)} width={680}>
        {detail && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="ID">{detail.id}</Descriptions.Item>
              <Descriptions.Item label="级别">
                <Tag color={levelColor[detail.level] || 'default'}>{detail.level}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="时间">{new Date(detail.created_at).toLocaleString('zh-CN')}</Descriptions.Item>
              <Descriptions.Item label="Logger">{detail.logger_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="Request ID" span={2}>{detail.request_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="Event" span={2}>{detail.event || '-'}</Descriptions.Item>
              <Descriptions.Item label="消息" span={2}>
                <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{detail.message || '-'}</pre>
              </Descriptions.Item>
            </Descriptions>

            {detail.context && Object.keys(detail.context).length > 0 && (
              <Card size="small" title="上下文">
                <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, fontSize: 12, maxHeight: 300, overflow: 'auto' }}>
                  {JSON.stringify(detail.context, null, 2)}
                </pre>
              </Card>
            )}

            {detail.traceback && (
              <Card size="small" title="Traceback">
                <pre style={{ background: '#fff1f0', padding: 12, borderRadius: 4, fontSize: 12, maxHeight: 400, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                  {detail.traceback}
                </pre>
              </Card>
            )}
          </Space>
        )}
      </Drawer>
    </div>
  )
}

export default MonitorErrors
