import { Row, Col, Card, Statistic, Table, Tag, Tooltip, Select, Space } from 'antd'
import {
  ApiOutlined, ThunderboltOutlined, ClockCircleOutlined, WarningOutlined,
} from '@ant-design/icons'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { LineChart } from '@/components/Chart'
import { getApiMonitor } from '@/api'

const ApiMonitor = () => {
  const [hours, setHours] = useState(24)

  const { data, refetch } = useQuery({
    queryKey: ['monitorApi', hours],
    queryFn: () => getApiMonitor(hours),
    refetchInterval: 30000,
  })

  const apiData = (data?.data || {}) as Record<string, any>

  const totalRequests = apiData.total_requests ?? 0
  const avgLatency = apiData.avg_latency ?? 0
  const errorRate = apiData.error_rate ?? 0
  const qps = apiData.qps ?? 0
  const latencyStats = apiData.latency_stats || {}

  const endpointColumns = [
    { title: '接口', dataIndex: 'endpoint', key: 'endpoint', ellipsis: true },
    {
      title: '方法', dataIndex: 'method', key: 'method', width: 80,
      render: (m: string) => {
        const colorMap: Record<string, string> = { GET: 'green', POST: 'blue', PUT: 'orange', DELETE: 'red', PATCH: 'purple' }
        return <Tag color={colorMap[m] || 'default'}>{m}</Tag>
      },
    },
    { title: '调用数', dataIndex: 'calls', key: 'calls', width: 100, sorter: (a: any, b: any) => a.calls - b.calls },
    {
      title: '平均耗时(ms)', dataIndex: 'avg_latency', key: 'avg_latency', width: 130,
      render: (v: number) => (
        <span style={{ color: v > 500 ? '#ff4d4f' : v > 200 ? '#fa8c16' : '#52c41a' }}>{v}ms</span>
      ),
      sorter: (a: any, b: any) => a.avg_latency - b.avg_latency,
    },
    {
      title: 'P95(ms)', dataIndex: 'p95', key: 'p95', width: 100,
      render: (v: number) => (
        <span style={{ color: v > 1000 ? '#ff4d4f' : v > 500 ? '#fa8c16' : '#52c41a' }}>{v}ms</span>
      ),
    },
    { title: '最大耗时(ms)', dataIndex: 'max_latency', key: 'max_latency', width: 110 },
    {
      title: '错误率', dataIndex: 'error_rate', key: 'error_rate', width: 100,
      render: (v: number) => (
        <span style={{ color: v > 5 ? '#ff4d4f' : v > 1 ? '#fa8c16' : '#52c41a' }}>{v}%</span>
      ),
    },
  ]

  const slowQueryColumns = [
    { title: '接口', dataIndex: 'endpoint', ellipsis: true },
    { title: '方法', dataIndex: 'method', width: 80 },
    { title: '最大耗时', dataIndex: 'max_latency', width: 110, render: (v: number) => <span style={{ color: '#ff4d4f' }}>{v}ms</span> },
    { title: 'P95', dataIndex: 'p95', width: 100, render: (v: number) => `${v}ms` },
    { title: '调用数', dataIndex: 'calls', width: 100 },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>API 性能监控</h2>
        <Space>
          <Select
            value={hours}
            style={{ width: 130 }}
            onChange={(v) => { setHours(v); refetch() }}
            options={[
              { label: '近 1 小时', value: 1 },
              { label: '近 6 小时', value: 6 },
              { label: '近 24 小时', value: 24 },
              { label: '近 7 天', value: 24 * 7 },
            ]}
          />
        </Space>
      </div>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="总请求数" value={totalRequests} prefix={<ApiOutlined style={{ color: '#1890ff' }} />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="QPS（窗口均值）" value={qps} prefix={<ThunderboltOutlined style={{ color: '#722ed1' }} />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="平均耗时"
              value={avgLatency}
              suffix="ms"
              valueStyle={{ color: avgLatency > 200 ? '#fa8c16' : '#52c41a' }}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="错误率"
              value={errorRate}
              suffix="%"
              valueStyle={{ color: errorRate > 5 ? '#ff4d4f' : errorRate > 1 ? '#fa8c16' : '#52c41a' }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={10}>
          <Card title="耗时分布（窗口聚合）" size="small">
            <Row gutter={16}>
              <Col span={8}>
                <Tooltip title="50% 请求耗时低于此值（粗估）">
                  <Card size="small" style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 22, fontWeight: 'bold', color: '#52c41a' }}>{latencyStats.p50 ?? 0}ms</div>
                    <div style={{ color: '#666' }}>P50</div>
                  </Card>
                </Tooltip>
              </Col>
              <Col span={8}>
                <Tooltip title="95% 请求耗时低于此值">
                  <Card size="small" style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 22, fontWeight: 'bold', color: '#fa8c16' }}>{latencyStats.p95 ?? 0}ms</div>
                    <div style={{ color: '#666' }}>P95</div>
                  </Card>
                </Tooltip>
              </Col>
              <Col span={8}>
                <Tooltip title="99% 请求耗时低于此值">
                  <Card size="small" style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 22, fontWeight: 'bold', color: '#ff4d4f' }}>{latencyStats.p99 ?? 0}ms</div>
                    <div style={{ color: '#666' }}>P99</div>
                  </Card>
                </Tooltip>
              </Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card title="QPS 趋势（每小时）" size="small">
            <LineChart
              data={(apiData.qps_trend || []) as { date: string; count: number }[]}
              color="#722ed1"
              height={180}
            />
          </Card>
        </Col>
      </Row>

      <Card title="接口排行（按调用数）" size="small" style={{ marginBottom: 16 }}>
        <Table
          columns={endpointColumns}
          dataSource={(apiData.endpoints || []) as any[]}
          rowKey={(r) => `${r.method}-${r.endpoint}`}
          pagination={{ pageSize: 10 }}
          size="small"
        />
      </Card>

      <Card title="慢接口（最大耗时 ≥ 1s）" size="small">
        <Table
          columns={slowQueryColumns}
          dataSource={(apiData.slow_queries || []) as any[]}
          rowKey={(r) => `${r.method}-${r.endpoint}`}
          pagination={{ pageSize: 10 }}
          size="small"
        />
      </Card>
    </div>
  )
}

export default ApiMonitor
