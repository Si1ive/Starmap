import { useState } from 'react'
import {
  Card, Row, Col, Statistic, Table, Tag, Button, Space, Select, Input,
  Descriptions, Drawer, Popconfirm, message, Tooltip,
} from 'antd'
import {
  ReloadOutlined, DeleteOutlined, EyeOutlined, ThunderboltOutlined,
  DollarOutlined, ClockCircleOutlined, WarningOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listLLMCalls, getLLMCallStats, getLLMCallDetail, deleteLLMCalls,
  type LLMCallSummary,
} from '@/api'

const { Search } = Input

const statusConfig: Record<string, { color: string; text: string }> = {
  success: { color: 'green', text: '成功' },
  error: { color: 'red', text: '失败' },
  timeout: { color: 'orange', text: '超时' },
}

const LLMMonitor = () => {
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [filters, setFilters] = useState<{ model?: string; status?: string; called_by?: string; keyword?: string }>({})
  const [statsHours, setStatsHours] = useState(24)
  const [detailId, setDetailId] = useState<string | undefined>()

  const { data: statsRes, refetch: refetchStats } = useQuery({
    queryKey: ['llmCallStats', statsHours],
    queryFn: () => getLLMCallStats(statsHours),
    refetchInterval: 30000,
  })

  const { data: listRes, refetch: refetchList, isLoading } = useQuery({
    queryKey: ['llmCallList', page, pageSize, filters],
    queryFn: () => listLLMCalls({ page, page_size: pageSize, ...filters }),
  })

  const { data: detailRes, isLoading: detailLoading } = useQuery({
    queryKey: ['llmCallDetail', detailId],
    queryFn: () => getLLMCallDetail(detailId ?? ''),
    enabled: !!detailId,
  })

  const cleanMutation = useMutation({
    mutationFn: (older_than_days: number) => deleteLLMCalls({ older_than_days }),
    onSuccess: (res) => {
      message.success(`已清理 ${res.data?.deleted ?? 0} 条记录`)
      qc.invalidateQueries({ queryKey: ['llmCallList'] })
      qc.invalidateQueries({ queryKey: ['llmCallStats'] })
    },
    onError: () => message.error('清理失败'),
  })

  const stats = statsRes?.data
  const list = listRes?.data

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '调用方',
      dataIndex: 'called_by',
      width: 130,
      render: (v: string) => <Tag color="geekblue">{v || '-'}</Tag>,
    },
    {
      title: '模型',
      dataIndex: 'model',
      width: 160,
      ellipsis: true,
    },
    {
      title: '用途',
      dataIndex: 'purpose',
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (s: string) => {
        const cfg = statusConfig[s] || { color: 'default', text: s }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    {
      title: 'Token (P/C/T)',
      key: 'tokens',
      width: 150,
      render: (_: unknown, r: LLMCallSummary) => `${r.prompt_tokens}/${r.completion_tokens}/${r.total_tokens}`,
    },
    {
      title: '耗时',
      dataIndex: 'latency_ms',
      width: 90,
      render: (v: number) => (
        <span style={{ color: v > 5000 ? '#ff4d4f' : v > 2000 ? '#fa8c16' : '#52c41a' }}>
          {v}ms
        </span>
      ),
    },
    {
      title: '成本(USD)',
      dataIndex: 'cost_usd',
      width: 100,
      render: (v: number) => v ? `$${Number(v).toFixed(4)}` : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      render: (_: unknown, r: LLMCallSummary) => (
        <Button type="link" icon={<EyeOutlined />} size="small" onClick={() => setDetailId(r.id)}>
          详情
        </Button>
      ),
    },
  ]

  const detail = detailRes?.data

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>LLM 调用监控</h2>
        <Space>
          <Select
            value={statsHours}
            style={{ width: 130 }}
            onChange={setStatsHours}
            options={[
              { label: '近 1 小时', value: 1 },
              { label: '近 6 小时', value: 6 },
              { label: '近 24 小时', value: 24 },
              { label: '近 7 天', value: 24 * 7 },
              { label: '近 30 天', value: 24 * 30 },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => { refetchStats(); refetchList() }}>刷新</Button>
          <Popconfirm
            title="清理 30 天前的调用记录？"
            onConfirm={() => cleanMutation.mutate(30)}
          >
            <Button danger icon={<DeleteOutlined />} loading={cleanMutation.isPending}>
              清理 30 天前
            </Button>
          </Popconfirm>
        </Space>
      </div>

      {/* 统计概览 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="调用总数"
              value={stats?.total_calls ?? 0}
              prefix={<ThunderboltOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="错误率"
              value={Number(((stats?.error_rate ?? 0) * 100).toFixed(2))}
              suffix="%"
              valueStyle={{ color: (stats?.error_rate ?? 0) > 0.05 ? '#ff4d4f' : '#52c41a' }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="总 Token"
              value={stats?.total_tokens ?? 0}
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="总成本"
              value={Number((stats?.total_cost_usd ?? 0).toFixed(4))}
              prefix={<DollarOutlined style={{ color: '#fa8c16' }} />}
              suffix="USD"
            />
          </Card>
        </Col>
      </Row>

      {/* 延迟分布 + 模型分布 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={10}>
          <Card title={<><ClockCircleOutlined /> 延迟分布</>} size="small">
            <Row gutter={16}>
              <Col span={8}>
                <Tooltip title="50% 调用在此时间内完成">
                  <Card size="small" style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 22, fontWeight: 'bold', color: '#52c41a' }}>{stats?.p50_latency_ms ?? 0}ms</div>
                    <div style={{ color: '#666' }}>P50</div>
                  </Card>
                </Tooltip>
              </Col>
              <Col span={8}>
                <Tooltip title="95% 调用在此时间内完成">
                  <Card size="small" style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 22, fontWeight: 'bold', color: '#fa8c16' }}>{stats?.p95_latency_ms ?? 0}ms</div>
                    <div style={{ color: '#666' }}>P95</div>
                  </Card>
                </Tooltip>
              </Col>
              <Col span={8}>
                <Tooltip title="99% 调用在此时间内完成">
                  <Card size="small" style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 22, fontWeight: 'bold', color: '#ff4d4f' }}>{stats?.p99_latency_ms ?? 0}ms</div>
                    <div style={{ color: '#666' }}>P99</div>
                  </Card>
                </Tooltip>
              </Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card title="按模型统计" size="small">
            <Table
              size="small"
              pagination={false}
              rowKey="model"
              dataSource={stats?.by_model || []}
              columns={[
                { title: '模型', dataIndex: 'model' },
                { title: '调用数', dataIndex: 'count', width: 80 },
                { title: 'Token', dataIndex: 'tokens', width: 100 },
                { title: '成本', dataIndex: 'cost_usd', width: 100, render: (v: number) => `$${Number(v).toFixed(4)}` },
                { title: '错误', dataIndex: 'errors', width: 70, render: (v: number) => v ? <Tag color="red">{v}</Tag> : v },
              ]}
            />
          </Card>
        </Col>
      </Row>

      {/* 列表 + 过滤 */}
      <Card
        size="small"
        title="调用明细"
        extra={
          <Space>
            <Input
              placeholder="模型"
              allowClear
              style={{ width: 150 }}
              onChange={(e) => setFilters({ ...filters, model: e.target.value || undefined })}
            />
            <Select
              placeholder="状态"
              allowClear
              style={{ width: 110 }}
              onChange={(v) => setFilters({ ...filters, status: v })}
              options={[
                { label: '成功', value: 'success' },
                { label: '失败', value: 'error' },
                { label: '超时', value: 'timeout' },
              ]}
            />
            <Input
              placeholder="调用方"
              allowClear
              style={{ width: 150 }}
              onChange={(e) => setFilters({ ...filters, called_by: e.target.value || undefined })}
            />
            <Search
              placeholder="搜索响应"
              allowClear
              style={{ width: 200 }}
              onSearch={(v) => setFilters({ ...filters, keyword: v || undefined })}
            />
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

      <Drawer
        title="LLM 调用详情"
        open={!!detailId}
        onClose={() => setDetailId(undefined)}
        width={720}
        loading={detailLoading}
      >
        {detail && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="ID" span={2}>{detail.id}</Descriptions.Item>
              <Descriptions.Item label="模型">{detail.model}</Descriptions.Item>
              <Descriptions.Item label="提供商">{detail.provider}</Descriptions.Item>
              <Descriptions.Item label="调用方">{detail.called_by || '-'}</Descriptions.Item>
              <Descriptions.Item label="用途">{detail.purpose || '-'}</Descriptions.Item>
              <Descriptions.Item label="Run ID">{detail.run_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="模型 Trace">{detail.trace_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={statusConfig[detail.status]?.color}>{statusConfig[detail.status]?.text}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="耗时">{detail.latency_ms} ms</Descriptions.Item>
              <Descriptions.Item label="Token (P/C/T)">{detail.prompt_tokens}/{detail.completion_tokens}/{detail.total_tokens}</Descriptions.Item>
              <Descriptions.Item label="成本">${Number(detail.cost_usd ?? 0).toFixed(6)}</Descriptions.Item>
              <Descriptions.Item label="时间" span={2}>{detail.created_at && new Date(detail.created_at).toLocaleString('zh-CN')}</Descriptions.Item>
              {detail.error_msg && (
                <Descriptions.Item label="错误信息" span={2}>
                  <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto', margin: 0 }}>{detail.error_msg}</pre>
                </Descriptions.Item>
              )}
            </Descriptions>

            <Card size="small" title="请求参数">
              <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, fontSize: 12, maxHeight: 200, overflow: 'auto' }}>
                {JSON.stringify(detail.request_params || {}, null, 2)}
              </pre>
            </Card>

            <Card size="small" title="请求 Messages">
              {(detail.request_messages || []).map((m, i) => (
                <div key={i} style={{ marginBottom: 12 }}>
                  <Tag color={m.role === 'system' ? 'purple' : m.role === 'user' ? 'blue' : 'green'}>{m.role}</Tag>
                  <pre style={{ background: '#fafafa', padding: 8, borderRadius: 4, fontSize: 12, marginTop: 4, whiteSpace: 'pre-wrap' }}>
                    {m.content}
                  </pre>
                </div>
              ))}
            </Card>

            <Card size="small" title="响应文本">
              <pre style={{ background: '#fafafa', padding: 12, borderRadius: 4, fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 400, overflow: 'auto' }}>
                {detail.response_text || '-'}
              </pre>
            </Card>
          </Space>
        )}
      </Drawer>
    </div>
  )
}

export default LLMMonitor
