import { useState, useEffect, useRef } from 'react'
import { Card, Table, Tag, Select, Input, Row, Col, Statistic, Badge, Space, Button, message } from 'antd'
import { SearchOutlined, ExclamationCircleOutlined, WarningOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getCrawlerLogs, getCrawlerLogAnalysis } from '@/api'
import type { CrawlerLog } from '@/types'

const CrawlerLogs = () => {
  const [params, setParams] = useState<Record<string, unknown>>({ page: 1, page_size: 50 })
  const [searchText, setSearchText] = useState('')
  const wsRef = useRef<WebSocket | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['crawlerLogs', params],
    queryFn: () => getCrawlerLogs(params as any),
  })

  const { data: analysisData } = useQuery({
    queryKey: ['crawlerLogAnalysis'],
    queryFn: () => getCrawlerLogAnalysis(7),
  })

  const logs = (data?.data?.items || []) as CrawlerLog[]
  const total = data?.data?.total || 0
  const analysis = (analysisData?.data || {}) as Record<string, any>

  // WebSocket 实时日志连接
  const connectWebSocket = () => {
    const wsUrl = `ws://localhost:8000/api/v1/admin/crawler/logs/stream`
    try {
      wsRef.current = new WebSocket(wsUrl)
      wsRef.current.onopen = () => message.success('实时日志连接已建立')
      wsRef.current.onmessage = (event) => {
        // 实时日志推送处理
        console.log('WS log:', event.data)
      }
      wsRef.current.onerror = () => message.error('WebSocket连接失败')
      wsRef.current.onclose = () => message.info('实时日志连接已断开')
    } catch {
      message.warning('WebSocket连接不可用')
    }
  }

  useEffect(() => {
    return () => {
      wsRef.current?.close()
    }
  }, [])

  const levelColors: Record<string, string> = {
    INFO: 'blue',
    WARNING: 'orange',
    ERROR: 'red',
    CRITICAL: '#cf1322',
    DEBUG: 'default',
  }

  const statusColors: Record<string, string> = {
    success: 'success',
    failed: 'error',
    skipped: 'warning',
    pending: 'default',
  }

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '级别',
      dataIndex: 'level',
      width: 80,
      render: (l: string) => <Tag color={levelColors[l] || 'default'}>{l}</Tag>,
    },
    {
      title: '阶段',
      dataIndex: 'stage',
      width: 80,
      render: (s: string) => s || '-',
    },
    {
      title: '资源名称',
      dataIndex: 'resource_name',
      width: 180,
      ellipsis: true,
      render: (n: string, r: CrawlerLog) => (
        <a href={r.resource_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12 }}>
          {n || r.resource_url || '-'}
        </a>
      ),
    },
    {
      title: '类型',
      dataIndex: 'resource_type',
      width: 80,
      render: (t: string) => {
        const map: Record<string, string> = { person: '人物', work: '作品', page: '页面' }
        return <Tag>{map[t] || t || '-'}</Tag>
      },
    },
    {
      title: '操作',
      dataIndex: 'action',
      width: 80,
      render: (a: string) => a || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (s: string) => <Tag color={statusColors[s] || 'default'}>{s || '-'}</Tag>,
    },
    {
      title: '耗时',
      dataIndex: 'duration_ms',
      width: 80,
      render: (v: number) => v ? (
        <span style={{ color: v > 5000 ? '#ff4d4f' : v > 2000 ? '#fa8c16' : '#52c41a' }}>{v}ms</span>
      ) : '-',
    },
    {
      title: '消息',
      dataIndex: 'message',
      ellipsis: true,
      render: (m: string) => m || '-',
    },
    {
      title: '重试',
      dataIndex: 'retry_count',
      width: 60,
      render: (v: number) => v ? <Badge count={v} style={{ backgroundColor: '#fa8c16' }} /> : '-',
    },
  ]

  const stats = analysis.stats || { total: 0, errors: 0, warnings: 0, success_rate: 0 }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>爬虫日志</h2>
        <Button onClick={connectWebSocket}>连接实时日志</Button>
      </div>

      {/* 统计 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={6}>
          <Card size="small"><Statistic title="总日志" value={stats.total || total} /></Card>
        </Col>
        <Col xs={6}>
          <Card size="small">
            <Statistic title="错误" value={stats.errors || 0} valueStyle={{ color: '#ff4d4f' }} prefix={<ExclamationCircleOutlined />} />
          </Card>
        </Col>
        <Col xs={6}>
          <Card size="small">
            <Statistic title="警告" value={stats.warnings || 0} valueStyle={{ color: '#fa8c16' }} prefix={<WarningOutlined />} />
          </Card>
        </Col>
        <Col xs={6}>
          <Card size="small">
            <Statistic title="成功率" value={stats.success_rate || 0} suffix="%" valueStyle={{ color: '#52c41a' }} prefix={<CheckCircleOutlined />} />
          </Card>
        </Col>
      </Row>

      {/* 筛选 */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            value={params.level as string || 'all'}
            onChange={(v) => setParams((p) => ({ ...p, level: v === 'all' ? undefined : v }))}
            style={{ width: 120 }}
            options={[
              { label: '全部级别', value: 'all' },
              { label: 'INFO', value: 'INFO' },
              { label: 'WARNING', value: 'WARNING' },
              { label: 'ERROR', value: 'ERROR' },
              { label: 'CRITICAL', value: 'CRITICAL' },
            ]}
          />
          <Select
            value={params.status as string || 'all'}
            onChange={(v) => setParams((p) => ({ ...p, status: v === 'all' ? undefined : v }))}
            style={{ width: 120 }}
            options={[
              { label: '全部状态', value: 'all' },
              { label: '成功', value: 'success' },
              { label: '失败', value: 'failed' },
              { label: '跳过', value: 'skipped' },
            ]}
          />
          <Select
            value={params.resource_type as string || 'all'}
            onChange={(v) => setParams((p) => ({ ...p, resource_type: v === 'all' ? undefined : v }))}
            style={{ width: 120 }}
            options={[
              { label: '全部类型', value: 'all' },
              { label: '人物', value: 'person' },
              { label: '作品', value: 'work' },
              { label: '页面', value: 'page' },
            ]}
          />
          <Input
            placeholder="搜索消息内容"
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{ width: 200 }}
            allowClear
          />
        </Space>
      </Card>

      {/* 日志列表 */}
      <Card>
        <Table
          columns={columns}
          dataSource={logs as any[]}
          rowKey="id"
          loading={isLoading}
          size="small"
          scroll={{ x: 1200 }}
          pagination={{
            current: params.page as number || 1,
            pageSize: params.page_size as number || 50,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
          }}
          onChange={(pagination) => setParams((p) => ({ ...p, page: pagination.current || 1, page_size: pagination.pageSize || 50 }))}
        />
      </Card>
    </div>
  )
}

export default CrawlerLogs