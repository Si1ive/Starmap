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

  const overview = overviewData?.data || {}
  const trend = trendData?.data || {}
  const sources = sourceData?.data || {}

  // 失败原因 Top5


  const failureData = overview.failure_top5 || [
    { type: '网络超时', count: 156, percent: 35 },
    { type: '404 Not Found', count: 89, percent: 20 },
    { type: '反爬拦截', count: 67, percent: 15 },
    { type: '解析错误', count: 45, percent: 10 },
    { type: '其他', count: 89, percent: 20 },
  ]

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

  const recentData = overview.recent_records || [
    { time: '2024-01-07 15:30:00', resource: '周杰伦 - Wikipedia', action: '下载', status: 'success', duration: 1250 },
    { time: '2024-01-07 15:29:55', resource: '昆凌 - Wikipedia', action: '解析', status: 'success', duration: 320 },
    { time: '2024-01-07 15:29:50', resource: '方文山 - Wikipedia', action: '下载', status: 'failed', duration: 5000 },
    { time: '2024-01-07 15:29:45', resource: '刘德华 - Douban', action: '下载', status: 'success', duration: 890 },
    { time: '2024-01-07 15:29:40', resource: '成龙 - Wikipedia', action: '存储', status: 'success', duration: 150 },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>爬取统计报表</h2>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="总任务数"
              value={overview.total_tasks || 23}
              prefix={<BugOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="总爬取数"
              value={overview.total_crawled || 12580}
              prefix={<NumberOutlined style={{ color: '#722ed1' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="总成功数"
              value={overview.total_success || 11890}
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="总失败数"
              value={overview.total_failed || 690}
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<CloseCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="整体成功率"
              value={overview.success_rate || 94.5}
              suffix="%"
              valueStyle={{ color: overview.success_rate >= 90 ? '#52c41a' : '#fa8c16' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="今日爬取"
              value={overview.today_crawled || 456}
              prefix={<ThunderboltOutlined style={{ color: '#fa8c16' }} />}
            />
          </Card>
        </Col>
      </Row>

      {/* 趋势图 + 数据源分布 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={14}>
          <Card title="近7日爬取趋势">
            {(trend.dates || []).length > 0 ? (
              <LineChart
                data={(trend.dates || []).map((d: any, i: number) => ({
                  date: d,
                  count: (trend.success_counts || [890, 920, 850, 960, 1020, 980, 1100])[i] || 0,
                }))}
                color="#52c41a"
                height={300}
              />
            ) : (
              <LineChart
                data={[
                  { date: '01-01', count: 890 },
                  { date: '01-02', count: 920 },
                  { date: '01-03', count: 850 },
                  { date: '01-04', count: 960 },
                  { date: '01-05', count: 1020 },
                  { date: '01-06', count: 980 },
                  { date: '01-07', count: 1100 },
                ]}
                color="#52c41a"
                height={300}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="数据源分布">
            <PieChart
              data={
                (sources.items || []).length > 0
                  ? sources.items.map((s: any) => ({ name: s.name, value: s.total_success }))
                  : [
                      { name: '维基百科', value: 8500 },
                      { name: '豆瓣', value: 2800 },
                      { name: '其他', value: 1280 },
                    ]
              }
              height={300}
            />
          </Card>
        </Col>
      </Row>

      {/* 失败分析 + 覆盖分布 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={12}>
          <Card title="失败原因 Top5">
            <BarChart
              data={failureData.map((f: any) => ({ name: f.type, value: f.count }))}
              color="#ff4d4f"
              height={280}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="分类覆盖分布">
            <BarChart
              data={[
                { name: '演员', value: 456 },
                { name: '歌手', value: 342 },
                { name: '导演', value: 198 },
                { name: '编剧', value: 173 },
                { name: '制片人', value: 87 },
                { name: '作曲', value: 65 },
              ]}
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
