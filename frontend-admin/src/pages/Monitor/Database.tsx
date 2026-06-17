import { Row, Col, Card, Statistic, Table, Tag, Progress, Space, Select } from 'antd'
import {
  DatabaseOutlined, CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined,
  HddOutlined, FundOutlined,
} from '@ant-design/icons'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { LineChart } from '@/components/Chart'
import { getDatabaseMonitor, getSystemMetrics } from '@/api'

interface DBStatus {
  name: string
  type: string
  status: 'connected' | 'disconnected' | 'warning' | string
  version?: string
  uptime?: string
  connections?: number
  max_connections?: number
  size?: string
  operations_per_sec?: number
  last_check?: string
}

const DatabaseMonitor = () => {
  const [hours, setHours] = useState(24)

  const { data: dbRes } = useQuery({
    queryKey: ['monitorDatabase'],
    queryFn: getDatabaseMonitor,
    refetchInterval: 30000,
  })

  const { data: metricsRes } = useQuery({
    queryKey: ['systemMetrics', hours],
    queryFn: () => getSystemMetrics(hours),
    refetchInterval: 30000,
  })

  const dbData = (dbRes?.data || {}) as Record<string, any>
  const databases: DBStatus[] = (dbData.databases || []) as DBStatus[]

  const metrics = metricsRes?.data
  const latest = metrics?.latest
  const series = metrics?.series || []

  const getStatusTag = (status: string) => {
    if (status === 'connected') return <Tag color="success">已连接</Tag>
    if (status === 'warning') return <Tag color="warning">警告</Tag>
    return <Tag color="error">断开</Tag>
  }

  const performanceColumns = [
    { title: '数据库', dataIndex: 'name', width: 120 },
    { title: '类型', dataIndex: 'type', width: 100 },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (s: string) => getStatusTag(s),
    },
    { title: '版本', dataIndex: 'version', width: 130 },
    {
      title: '连接数', dataIndex: 'connections', width: 200,
      render: (v: number, r: DBStatus) => {
        const max = r.max_connections || 0
        if (!max) return v ?? '-'
        return (
          <span>
            {v}/{max}
            <Progress
              percent={(v / max) * 100}
              size="small"
              status={v / max > 0.8 ? 'exception' : 'normal'}
              style={{ marginLeft: 8, width: 100 }}
            />
          </span>
        )
      },
    },
    { title: '数据量', dataIndex: 'size', width: 130 },
    { title: 'OPS', dataIndex: 'operations_per_sec', width: 100 },
    {
      title: '最后检查', dataIndex: 'last_check', width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
  ]

  // 时序数据：CPU / 内存
  const cpuSeries = series.map((s) => ({ date: s.sampled_at, count: Math.round(s.cpu_percent) }))
  const memSeries = series.map((s) => ({ date: s.sampled_at, count: Math.round(s.mem_percent) }))
  const procSeries = series.map((s) => ({ date: s.sampled_at, count: Math.round(s.process_rss_mb) }))

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>数据库与资源监控</h2>
        <Space>
          <Select
            value={hours}
            style={{ width: 130 }}
            onChange={setHours}
            options={[
              { label: '近 1 小时', value: 1 },
              { label: '近 24 小时', value: 24 },
              { label: '近 7 天', value: 24 * 7 },
            ]}
          />
        </Space>
      </div>

      {/* 数据库探活 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="数据库总数" value={databases.length}
              prefix={<DatabaseOutlined style={{ color: '#1890ff' }} />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="已连接" value={databases.filter((d) => d.status === 'connected').length}
              valueStyle={{ color: '#52c41a' }} prefix={<CheckCircleOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="警告" value={databases.filter((d) => d.status === 'warning').length}
              valueStyle={{ color: '#fa8c16' }} prefix={<ExclamationCircleOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="断开" value={databases.filter((d) => d.status === 'disconnected').length}
              valueStyle={{ color: '#ff4d4f' }} prefix={<CloseCircleOutlined />} />
          </Card>
        </Col>
      </Row>

      <Card title="数据库连接状态" size="small" style={{ marginBottom: 16 }}>
        <Table columns={performanceColumns} dataSource={databases} rowKey="name" pagination={false} size="small" />
      </Card>

      {/* 系统资源 */}
      <h3>系统资源（{latest ? `最新采样：${new Date(latest.sampled_at).toLocaleString('zh-CN')}` : '暂无数据'}）</h3>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8} lg={6}>
          <Card size="small">
            <Statistic title="CPU 使用率" value={latest?.cpu_percent ?? 0} suffix="%"
              valueStyle={{ color: (latest?.cpu_percent ?? 0) > 80 ? '#ff4d4f' : '#52c41a' }}
              prefix={<FundOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={6}>
          <Card size="small">
            <Statistic
              title="内存使用率"
              value={latest?.mem_percent ?? 0}
              suffix="%"
              valueStyle={{ color: (latest?.mem_percent ?? 0) > 85 ? '#ff4d4f' : '#52c41a' }}
            />
            <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>
              {latest?.mem_used_mb?.toFixed(0) ?? 0} / {latest?.mem_total_mb?.toFixed(0) ?? 0} MB
            </div>
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={6}>
          <Card size="small">
            <Statistic title="磁盘使用率" value={latest?.disk_percent ?? 0} suffix="%"
              valueStyle={{ color: (latest?.disk_percent ?? 0) > 85 ? '#ff4d4f' : '#52c41a' }}
              prefix={<HddOutlined />} />
            <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>
              {latest?.disk_used_gb?.toFixed(1) ?? 0} / {latest?.disk_total_gb?.toFixed(1) ?? 0} GB
            </div>
          </Card>
        </Col>
        <Col xs={12} sm={8} lg={6}>
          <Card size="small">
            <Statistic title="进程内存(RSS)" value={Number((latest?.process_rss_mb ?? 0).toFixed(1))} suffix="MB" />
            <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>
              进程 CPU: {latest?.process_cpu_percent?.toFixed(1) ?? 0}%
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card title="CPU 使用率趋势" size="small">
            <LineChart data={cpuSeries} color="#1890ff" height={200} />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="内存使用率趋势" size="small">
            <LineChart data={memSeries} color="#52c41a" height={200} />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="进程 RSS 趋势 (MB)" size="small">
            <LineChart data={procSeries} color="#fa8c16" height={200} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default DatabaseMonitor
