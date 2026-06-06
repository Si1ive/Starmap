import { Row, Col, Card, Statistic, Table, Tag } from 'antd'
import {
  BugOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ThunderboltOutlined,

  NumberOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { LineChart, PieChart, BarChart } from '@/components/Chart'
import adminClient from '@/api/client'

// 调用后端统计 API
const getCrawlerStats = () => adminClient.get('/crawler/stats/overview')
const getCrawlerTrend = (days = 7) => adminClient.get('/crawler/stats/trend', { params: { days } })
const getSourceComparison = (days = 7) => adminClient.get('/crawler/stats/sources', { params: { days } })

const CrawlerStats = () => {
  const { data: overviewData } = useQuery({
    queryKey: ['crawlerStatsOverview'],
    queryFn: getCrawlerStats,
  })

  const { data: trendData } = useQuery({
    queryKey: ['crawlerStatsTrend'],
    queryFn: () => getCrawlerTrend(7),
  })

  const { data: sourceData } = useQuery({
    queryKey: ['crawlerSourceComparison'],
    queryFn: () => getSourceComparison(7),
  })

  const overview = (overviewData?.data || {}) as Record<string, any>
  const trend = Array.isArray(trendData?.data) ? trendData.data : []
  const sources = Array.isArray(sourceData?.data) ? sourceData.data : []

  const trendChartData = trend.map((item: any) => ({
    date: item.date,
    count: item.successes || 0,
  }))
  const sourceChartData = sources.map((source: any) => ({
    name: source.name,
    value: source.success_requests || source.total_requests || 0,
  }))
  const failureData = sources
    .filter((source: any) => (source.failed_requests || 0) > 0)
    .map((source: any) => ({ name: source.name, value: source.failed_requests || 0 }))
  const categoryData = overview.category_distribution || []

  // 最近爬取记录
  const recentColumns = [
    { title: '时间', dataIndex: 'time', width: 180 },
    { title: '资源', dataIndex: 'resource', ellipsis: true },
    { title: '操作', dataIndex: 'action', width: 100 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: string) => {
        const map: Record<string, { color: string; text: string }> = {
          success: { color: 'success', text: '成功' },
          failed: { color: 'error', text: '失败' },
          skipped: { color: 'warning', text: '跳过' },
        }
        const config = map[s] || { color: 'default', text: s }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    { title: '耗时', dataIndex: 'duration', width: 100, render: (v: number) => `${v}ms` },
  ]

  const recentData = overview.recent_records || []

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>爬取统计报表</h2>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="总任务数"
              value={overview.total_tasks || 0}
              prefix={<BugOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="总请求数"
              value={overview.total_requests || 0}
              prefix={<NumberOutlined style={{ color: '#722ed1' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="总成功数"
              value={overview.total_success || 0}
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="总失败数"
              value={overview.total_failed || 0}
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<CloseCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="整体成功率"
              value={overview.overall_success_rate || 0}
              suffix="%"
              valueStyle={{ color: (overview.overall_success_rate || 0) >= 90 ? '#52c41a' : '#fa8c16' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="今日爬取"
              value={overview.today_requests || 0}
              prefix={<ThunderboltOutlined style={{ color: '#fa8c16' }} />}
            />
          </Card>
        </Col>
      </Row>

      {/* 趋势图 + 数据源分布 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={14}>
          <Card title="近7日爬取趋势">
            <LineChart data={trendChartData} color="#52c41a" height={300} />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="数据源分布">
            <PieChart data={sourceChartData} height={300} />
          </Card>
        </Col>
      </Row>

      {/* 失败分析 + 覆盖分布 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={12}>
          <Card title="失败请求源分布">
            <BarChart
              data={failureData}
              color="#ff4d4f"
              height={280}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="分类覆盖分布">
            <BarChart
              data={categoryData}
              color="#1890ff"
              height={280}
            />
          </Card>
        </Col>
      </Row>

      {/* 最近爬取记录 */}
      <Card title="最近爬取记录">
        <Table
          columns={recentColumns}
          dataSource={recentData}
          rowKey="time"
          pagination={false}
          size="small"
        />
      </Card>
    </div>
  )
}

export default CrawlerStats
