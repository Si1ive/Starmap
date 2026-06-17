import { Card, Row, Col, Statistic, Table, Tag, Space } from 'antd'
import {
  ApiOutlined, DatabaseOutlined, WarningOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  getApiMonitor, getDatabaseMonitor, getServiceLogs,
  getSystemMetrics, getLLMCallStats,
} from '@/api'

const levelColor: Record<string, string> = {
  ERROR: '#ff4d4f', WARNING: '#fa8c16', INFO: '#1890ff',
}

const MonitorOverview = () => {
  const navigate = useNavigate()

  const { data: apiData } = useQuery({ queryKey: ['apiMonitor'], queryFn: () => getApiMonitor(24) })
  const { data: dbData } = useQuery({ queryKey: ['dbMonitor'], queryFn: getDatabaseMonitor })
  const { data: errorData } = useQuery({
    queryKey: ['errorLogsOverview'],
    queryFn: () => getServiceLogs({ level: 'ERROR', page: 1, page_size: 5 }),
  })
  const { data: metricsRes } = useQuery({
    queryKey: ['systemMetricsOverview'],
    queryFn: () => getSystemMetrics(1),
    refetchInterval: 30000,
  })
  const { data: llmStatsRes } = useQuery({
    queryKey: ['llmStatsOverview'],
    queryFn: () => getLLMCallStats(24),
    refetchInterval: 60000,
  })

  const api = (apiData?.data || {}) as Record<string, any>
  const db = (dbData?.data || {}) as Record<string, any>
  const errors = (errorData?.data || {}) as Record<string, any>
  const metrics = metricsRes?.data?.latest
  const llmStats = llmStatsRes?.data

  const errorColumns = [
    {
      title: '时间', dataIndex: 'created_at', width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '级别', dataIndex: 'level', width: 90,
      render: (l: string) => <Tag color={levelColor[l] || 'default'}>{l}</Tag>,
    },
    { title: 'Logger', dataIndex: 'logger_name', width: 180, ellipsis: true },
    { title: '消息', dataIndex: 'message', ellipsis: true },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>系统监控总览</h2>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate('/admin/monitor/api')}>
            <Statistic
              title="API 请求数（近 24h）"
              value={api?.total_requests || 0}
              prefix={<ApiOutlined style={{ color: '#1890ff' }} />}
            />
            <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
              平均耗时: {api?.avg_latency || 0}ms · 错误率: {api?.error_rate || 0}%
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate('/admin/monitor/llm')}>
            <Statistic
              title="LLM 调用（近 24h）"
              value={llmStats?.total_calls || 0}
              prefix={<ThunderboltOutlined style={{ color: '#722ed1' }} />}
            />
            <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
              成本: ${Number(llmStats?.total_cost_usd ?? 0).toFixed(4)} · Token: {llmStats?.total_tokens ?? 0}
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate('/admin/monitor/database')}>
            <Statistic
              title="数据库连接"
              value={db?.status === 'connected' ? '正常' : '异常'}
              valueStyle={{ color: db?.status === 'connected' ? '#52c41a' : '#ff4d4f' }}
              prefix={<DatabaseOutlined />}
            />
            <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
              已连接: {(db?.databases || []).filter((d: any) => d.status === 'connected').length} 个
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable onClick={() => navigate('/admin/monitor/errors')}>
            <Statistic
              title="错误日志（近 24h）"
              value={errors?.total ?? 0}
              valueStyle={{ color: (errors?.total ?? 0) > 0 ? '#ff4d4f' : '#52c41a' }}
              prefix={<WarningOutlined />}
            />
            <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
              点击查看详情
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={12}>
          <Card title="系统资源" size="small">
            {metrics ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Row gutter={16}>
                  <Col span={8}>
                    <Statistic title="CPU" value={metrics.cpu_percent} suffix="%" />
                  </Col>
                  <Col span={8}>
                    <Statistic title="内存" value={metrics.mem_percent} suffix="%" />
                  </Col>
                  <Col span={8}>
                    <Statistic title="磁盘" value={metrics.disk_percent} suffix="%" />
                  </Col>
                </Row>
                <div style={{ color: '#999', fontSize: 12, marginTop: 8 }}>
                  进程 RSS: {metrics.process_rss_mb?.toFixed(1)} MB · 进程 CPU: {metrics.process_cpu_percent?.toFixed(1)}%
                </div>
              </Space>
            ) : (
              <div style={{ color: '#999' }}>资源采样器正在启动...（每 10 秒一次）</div>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="LLM 调用延迟" size="small">
            {llmStats ? (
              <Row gutter={16}>
                <Col span={8}>
                  <Statistic title="P50" value={llmStats.p50_latency_ms} suffix="ms" valueStyle={{ color: '#52c41a' }} />
                </Col>
                <Col span={8}>
                  <Statistic title="P95" value={llmStats.p95_latency_ms} suffix="ms" valueStyle={{ color: '#fa8c16' }} />
                </Col>
                <Col span={8}>
                  <Statistic title="P99" value={llmStats.p99_latency_ms} suffix="ms" valueStyle={{ color: '#ff4d4f' }} />
                </Col>
              </Row>
            ) : (
              <div style={{ color: '#999' }}>暂无 LLM 调用记录</div>
            )}
          </Card>
        </Col>
      </Row>

      <Card title="最近错误日志（点击查看详情）" extra={<a onClick={() => navigate('/admin/monitor/errors')}>查看更多</a>}>
        <Table
          columns={errorColumns}
          dataSource={(errors?.items as any[]) || []}
          rowKey="id"
          pagination={false}
          size="small"
        />
      </Card>
    </div>
  )
}

export default MonitorOverview
