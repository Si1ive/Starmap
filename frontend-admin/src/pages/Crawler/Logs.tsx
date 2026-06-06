import { useState, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Card, Table, Tag, Select, Input, Row, Col, Statistic, Badge, Space, Button } from 'antd'
import { SearchOutlined, ExclamationCircleOutlined, WarningOutlined, CheckCircleOutlined, DisconnectOutlined, LinkOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getCrawlerLogs, getCrawlerLogAnalysis } from '@/api'
import type { CrawlerLog } from '@/types'

const CrawlerLogs = () => {
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const initialTaskId = searchParams.get('task_id') || undefined
  
  const [params, setParams] = useState<Record<string, unknown>>({ 
    page: 1, 
    page_size: 50,
    task_id: initialTaskId,
  })
  const [searchText, setSearchText] = useState('')
  const [realtimeLogs, setRealtimeLogs] = useState<CrawlerLog[]>([])
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected')
  const wsRef = useRef<WebSocket | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['crawlerLogs', params],
    queryFn: () => getCrawlerLogs(params as any),
  })

  const { data: analysisData } = useQuery({
    queryKey: ['crawlerLogAnalysis'],
    queryFn: () => getCrawlerLogAnalysis(7),
  })

  const persistedLogs = (data?.data?.items || []) as CrawlerLog[]
  const logs = [...realtimeLogs, ...persistedLogs]
    .filter((log, index, items) => items.findIndex((item) => String(item.id) === String(log.id)) === index)
    .filter((log) => {
      const keyword = searchText.trim().toLowerCase()
      if (!keyword) return true
      return [
        log.message,
        log.resource_name,
        log.resource_url,
        log.task_id,
        log.source_id,
        log.error_type,
        log.error_detail,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword))
    })
  const total = data?.data?.total || 0
  const analysis = (analysisData?.data || {}) as Record<string, any>

  const buildWebSocketUrl = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = new URL(`${protocol}//${window.location.host}/api/v1/admin/crawler/logs/stream`)
    if (params.task_id) url.searchParams.set('task_id', String(params.task_id))
    if (params.source_id) url.searchParams.set('source_id', String(params.source_id))
    if (params.level) url.searchParams.set('level', String(params.level))
    return url.toString()
  }

  const syncWebSocketFilters = () => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return
    wsRef.current.send(JSON.stringify({
      type: 'filter',
      task_ids: params.task_id ? [String(params.task_id)] : [],
      source_ids: params.source_id ? [String(params.source_id)] : [],
      levels: params.level ? [String(params.level)] : [],
    }))
  }

  const connectWebSocket = () => {
    wsRef.current?.close()
    setWsStatus('connecting')
    try {
      wsRef.current = new WebSocket(buildWebSocketUrl())
      wsRef.current.onopen = () => {
        setWsStatus('connected')
        syncWebSocketFilters()
      }
      wsRef.current.onmessage = (event) => {
        const messageData = JSON.parse(event.data)
        if (messageData.type !== 'log' || !messageData.data) return
        const log = messageData.data as CrawlerLog
        setRealtimeLogs((current) => {
          const logId = String(log.id || `${log.task_id}-${log.created_at}-${log.message}`)
          const normalizedLog = { ...log, id: logId }
          return [
            normalizedLog,
            ...current.filter((item) => String(item.id) !== logId),
          ].slice(0, 200)
        })
        queryClient.invalidateQueries({ queryKey: ['crawlerLogAnalysis'] })
      }
      wsRef.current.onerror = () => setWsStatus('disconnected')
      wsRef.current.onclose = () => setWsStatus('disconnected')
    } catch {
      setWsStatus('disconnected')
    }
  }

  useEffect(() => {
    connectWebSocket()
    return () => {
      wsRef.current?.close()
    }
  }, [])

  useEffect(() => {
    syncWebSocketFilters()
  }, [params.task_id, params.source_id, params.level])

  useEffect(() => {
    setRealtimeLogs([])
  }, [params.task_id, params.source_id, params.level, params.status, params.resource_type])

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

  const levelCounts = (analysis.level_distribution || []).reduce((acc: Record<string, number>, item: any) => {
    acc[item.level] = item.count
    return acc
  }, {})
  const statusCounts = (analysis.status_distribution || []).reduce((acc: Record<string, number>, item: any) => {
    acc[item.status] = item.count
    return acc
  }, {})
  const stats = {
    total,
    errors: levelCounts.ERROR || 0,
    warnings: levelCounts.WARNING || 0,
    success_rate: total ? Math.round(((statusCounts.success || 0) / total) * 1000) / 10 : 0,
  }
  const wsStatusConfig = {
    connected: { color: 'success', text: '实时已连接', icon: <LinkOutlined /> },
    connecting: { color: 'processing', text: '连接中', icon: <LinkOutlined /> },
    disconnected: { color: 'default', text: '实时未连接', icon: <DisconnectOutlined /> },
  }[wsStatus]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ margin: 0 }}>爬虫日志</h2>
          <Tag color={wsStatusConfig.color} icon={wsStatusConfig.icon}>
            {wsStatusConfig.text}
          </Tag>
          {initialTaskId && (
            <Tag color="blue">
              任务: {initialTaskId}
            </Tag>
          )}
        </div>
        <Button onClick={connectWebSocket} icon={<LinkOutlined />}>重连实时日志</Button>
      </div>

      {/* 统计 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={6}>
          <Card size="small"><Statistic title="总日志" value={stats.total} /></Card>
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
            placeholder="搜索当前页和实时日志"
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
