import { useState } from 'react'
import {
  Card, Row, Col, Statistic, Table, Tag, Button, Space, Select, Input,
  Descriptions, Drawer, Popconfirm, message, Tooltip, Progress,
} from 'antd'
import {
  ReloadOutlined, DeleteOutlined, EyeOutlined, AimOutlined,
  ClockCircleOutlined, WarningOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listVectorRecalls, getVectorRecallStats, deleteVectorRecalls,
  type VectorRecallItem, type VectorRecallTopResult,
} from '@/api'

const { Search } = Input

const statusConfig: Record<string, { color: string; text: string }> = {
  hit: { color: 'green', text: '命中' },
  miss: { color: 'orange', text: '无结果' },
  error: { color: 'red', text: '异常' },
}

const calledByConfig: Record<string, { color: string; text: string }> = {
  question: { color: 'blue', text: '题目' },
  knowledge_point: { color: 'geekblue', text: '知识点' },
}

// 分数配色：越高越绿
function scoreColor(score: number): string {
  if (score >= 0.75) return '#52c41a'
  if (score >= 0.6) return '#fa8c16'
  return '#ff4d4f'
}

// top-N 结果紧凑展示：rank + 章节名 + 分数条
function TopResultsCell({ results }: { results: VectorRecallTopResult[] }) {
  if (!results || results.length === 0) return <span style={{ color: '#999' }}>无召回</span>
  return (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      {results.map((r) => (
        <div key={r.rank} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Tag color={r.is_primary ? 'green' : 'default'} style={{ margin: 0, minWidth: 28, textAlign: 'center' }}>
            {r.rank + 1}
          </Tag>
          <span style={{ flex: 1, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {r.chapter_name || r.chapter_id}
          </span>
          <span style={{ fontFamily: 'monospace', fontSize: 12, color: scoreColor(r.score) }}>
            {r.score.toFixed(4)}
          </span>
        </div>
      ))}
    </Space>
  )
}

const VectorRecallMonitor = () => {
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [filters, setFilters] = useState<{ called_by?: string; status?: string; keyword?: string }>({})
  const [statsHours, setStatsHours] = useState(24)
  const [detail, setDetail] = useState<VectorRecallItem | null>(null)

  const { data: statsRes, refetch: refetchStats } = useQuery({
    queryKey: ['vecRecallStats', statsHours],
    queryFn: () => getVectorRecallStats(statsHours),
    refetchInterval: 30000,
  })

  const { data: listRes, refetch: refetchList, isLoading } = useQuery({
    queryKey: ['vecRecallList', page, pageSize, filters],
    queryFn: () => listVectorRecalls({ page, page_size: pageSize, ...filters }),
  })

  const cleanMutation = useMutation({
    mutationFn: (older_than_days: number) => deleteVectorRecalls({ older_than_days }),
    onSuccess: (res) => {
      message.success(`已清理 ${res.data?.deleted ?? 0} 条记录`)
      qc.invalidateQueries({ queryKey: ['vecRecallList'] })
      qc.invalidateQueries({ queryKey: ['vecRecallStats'] })
    },
    onError: () => message.error('清理失败'),
  })

  const stats = statsRes?.data
  const list = listRes?.data

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '-',
    },
    {
      title: '调用方',
      dataIndex: 'called_by',
      width: 90,
      render: (v: string) => {
        const cfg = calledByConfig[v] || { color: 'default', text: v || '-' }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    {
      title: '查询文本（入参）',
      dataIndex: 'query_text',
      ellipsis: true,
      render: (v: string) => <span style={{ fontSize: 12 }}>{v || '-'}</span>,
    },
    {
      title: '召回 Top 结果',
      key: 'top_results',
      width: 280,
      render: (_: unknown, r: VectorRecallItem) => <TopResultsCell results={r.top_results} />,
    },
    {
      title: '最高分',
      dataIndex: 'top_score',
      width: 90,
      render: (v: number, r: VectorRecallItem) => (
        <span style={{ fontFamily: 'monospace', color: scoreColor(v) }}>
          {v.toFixed(4)}{r.threshold_hit ? ' ✓' : ''}
        </span>
      ),
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
      title: '耗时',
      dataIndex: 'latency_ms',
      width: 80,
      render: (v: number) => `${v}ms`,
    },
    {
      title: '操作',
      key: 'actions',
      width: 70,
      render: (_: unknown, r: VectorRecallItem) => (
        <Button type="link" icon={<EyeOutlined />} size="small" onClick={() => setDetail(r)}>详情</Button>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>向量召回监控</h2>
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
          <Popconfirm title="清理 30 天前的召回记录？" onConfirm={() => cleanMutation.mutate(30)}>
            <Button danger icon={<DeleteOutlined />} loading={cleanMutation.isPending}>清理 30 天前</Button>
          </Popconfirm>
        </Space>
      </div>

      {/* 统计概览：召回率是核心 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="召回总次数"
              value={stats?.total_recalls ?? 0}
              prefix={<AimOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Tooltip title="有召回结果的比例（status=hit）">
              <Statistic
                title="命中率"
                value={Number(((stats?.hit_rate ?? 0) * 100).toFixed(1))}
                suffix="%"
                valueStyle={{ color: '#52c41a' }}
                prefix={<CheckCircleOutlined />}
              />
            </Tooltip>
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Tooltip title="最高分达到采信阈值的比例——真正有效的召回">
              <Statistic
                title="有效召回率"
                value={Number(((stats?.threshold_hit_rate ?? 0) * 100).toFixed(1))}
                suffix="%"
                valueStyle={{ color: (stats?.threshold_hit_rate ?? 0) < 0.5 ? '#fa8c16' : '#52c41a' }}
              />
            </Tooltip>
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="平均最高分"
              value={Number((stats?.avg_top_score ?? 0).toFixed(4))}
              valueStyle={{ color: scoreColor(stats?.avg_top_score ?? 0) }}
            />
          </Card>
        </Col>
      </Row>

      {/* 命中构成 + 延迟 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="召回构成" size="small">
            <Space size="large">
              <Statistic title="命中" value={stats?.hit_count ?? 0} valueStyle={{ color: '#52c41a', fontSize: 20 }} />
              <Statistic title="无结果" value={stats?.miss_count ?? 0} valueStyle={{ color: '#fa8c16', fontSize: 20 }} />
              <Statistic title="异常" value={stats?.error_count ?? 0} valueStyle={{ color: '#ff4d4f', fontSize: 20 }} prefix={<WarningOutlined />} />
            </Space>
            {(stats?.total_recalls ?? 0) > 0 && (
              <Progress
                style={{ marginTop: 12 }}
                percent={100}
                success={{ percent: Math.round(((stats?.hit_count ?? 0) / (stats?.total_recalls ?? 1)) * 100) }}
                showInfo={false}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title={<><ClockCircleOutlined /> 延迟</>} size="small">
            <Space size="large">
              <Statistic title="平均耗时" value={stats?.avg_latency_ms ?? 0} suffix="ms" />
              <Statistic title="P95 耗时" value={stats?.p95_latency_ms ?? 0} suffix="ms" valueStyle={{ color: '#fa8c16' }} />
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 明细 */}
      <Card
        size="small"
        title="召回明细"
        extra={
          <Space>
            <Select
              placeholder="调用方"
              allowClear
              style={{ width: 130 }}
              onChange={(v) => setFilters({ ...filters, called_by: v })}
              options={[
                { label: '题目', value: 'question' },
                { label: '知识点', value: 'knowledge_point' },
              ]}
            />
            <Select
              placeholder="状态"
              allowClear
              style={{ width: 110 }}
              onChange={(v) => setFilters({ ...filters, status: v })}
              options={[
                { label: '命中', value: 'hit' },
                { label: '无结果', value: 'miss' },
                { label: '异常', value: 'error' },
              ]}
            />
            <Search
              placeholder="搜索查询文本"
              allowClear
              style={{ width: 220 }}
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

      <Drawer title="向量召回详情" open={!!detail} onClose={() => setDetail(null)} width={720}>
        {detail && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="ID" span={2}>{detail.id}</Descriptions.Item>
              <Descriptions.Item label="调用方">
                <Tag color={calledByConfig[detail.called_by || '']?.color}>{calledByConfig[detail.called_by || '']?.text || detail.called_by || '-'}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="用途">{detail.purpose || '-'}</Descriptions.Item>
              <Descriptions.Item label="触发实体ID">{detail.query_entity_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="学科范围">{detail.subject_id || '全学科'}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={statusConfig[detail.status]?.color}>{statusConfig[detail.status]?.text}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="最高分">
                <span style={{ fontFamily: 'monospace', color: scoreColor(detail.top_score) }}>
                  {detail.top_score.toFixed(4)} {detail.threshold_hit ? '（达阈值）' : '（未达阈值）'}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="召回数">{detail.result_count}</Descriptions.Item>
              <Descriptions.Item label="耗时">{detail.latency_ms} ms</Descriptions.Item>
              <Descriptions.Item label="时间">{detail.created_at && new Date(detail.created_at).toLocaleString('zh-CN')}</Descriptions.Item>
              {detail.error_msg && (
                <Descriptions.Item label="错误信息" span={2}>
                  <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{detail.error_msg}</pre>
                </Descriptions.Item>
              )}
            </Descriptions>

            <Card size="small" title="查询文本（入参）">
              <pre style={{ background: '#fafafa', padding: 12, borderRadius: 4, fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>
                {detail.query_text || '-'}
              </pre>
            </Card>

            <Card size="small" title={`Top-${detail.top_results.length} 召回结果`}>
              <Table
                size="small"
                pagination={false}
                rowKey="rank"
                dataSource={detail.top_results}
                columns={[
                  { title: '#', dataIndex: 'rank', width: 50, render: (v: number) => v + 1 },
                  {
                    title: '章节', dataIndex: 'chapter_name',
                    render: (v: string, r: VectorRecallTopResult) => (
                      <span>
                        {v || r.chapter_id}
                        {r.is_primary && <Tag color="green" style={{ marginLeft: 8 }}>采信</Tag>}
                      </span>
                    ),
                  },
                  {
                    title: '分数', dataIndex: 'score', width: 100,
                    render: (v: number) => <span style={{ fontFamily: 'monospace', color: scoreColor(v) }}>{v.toFixed(4)}</span>,
                  },
                ]}
              />
            </Card>
          </Space>
        )}
      </Drawer>
    </div>
  )
}

export default VectorRecallMonitor
