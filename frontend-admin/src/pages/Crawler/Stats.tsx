import { Row, Col, Card, Statistic, Tag, Alert, List, Space } from 'antd'
import {
  FileOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ThunderboltOutlined,
  CloudDownloadOutlined,
  DatabaseOutlined,
  HddOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { LineChart, PieChart, BarChart } from '@/components/Chart'
import adminClient from '@/api/client'

// 调用后端统计 API
const getCrawlerStats = () => adminClient.get('/crawler/stats/overview')
const getCrawlerTrend = (days = 7) => adminClient.get('/crawler/stats/trend', { params: { days } })
const getSourceComparison = (days = 7) => adminClient.get('/crawler/stats/sources', { params: { days } })
const getOptimizationSuggestions = (days = 7) => adminClient.get('/crawler/stats/suggestions', { params: { days } })
const getFileTypeDistribution = () => adminClient.get('/crawler/stats/file-types')

const formatFileSize = (bytes?: number) => {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

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

  const { data: suggestionsData } = useQuery({
    queryKey: ['crawlerOptimizationSuggestions'],
    queryFn: () => getOptimizationSuggestions(7),
  })

  const { data: fileTypeData } = useQuery({
    queryKey: ['fileTypeDistribution'],
    queryFn: getFileTypeDistribution,
  })

  const overview = (overviewData?.data || {}) as Record<string, any>
  const trend = Array.isArray(trendData?.data) ? trendData.data : []
  const sources = Array.isArray(sourceData?.data) ? sourceData.data : []
  const suggestions = Array.isArray(suggestionsData?.data) ? suggestionsData.data : []
  const fileTypes = Array.isArray(fileTypeData?.data) ? fileTypeData.data : []

  // 趋势图数据
  const trendChartData = trend.map((item: any) => ({
    date: item.date,
    count: item.successes || 0,
  }))

  // 仓库分布数据
  const repoChartData = sources.map((source: any) => ({
    name: source.name,
    value: source.success || source.total || 0,
  }))

  // 失败分布数据
  const failureData = sources
    .filter((source: any) => (source.failed || 0) > 0)
    .map((source: any) => ({ name: source.name, value: source.failed || 0 }))

  // 文件类型分布
  const fileTypeChartData = fileTypes.map((item: any) => ({
    name: (item.name || '未知').toUpperCase(),
    value: item.value || 0,
  }))

  const severityConfig: Record<string, { color: string; text: string }> = {
    critical: { color: 'red', text: '严重' },
    warning: { color: 'orange', text: '警告' },
    info: { color: 'blue', text: '提示' },
  }

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>文件爬取统计</h2>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="总文件数"
              value={overview.total_files || 0}
              prefix={<FileOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="下载成功"
              value={overview.total_success || 0}
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="下载失败"
              value={overview.total_failed || 0}
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<CloseCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="成功率"
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
              title="今日下载"
              value={overview.today_files || 0}
              prefix={<ThunderboltOutlined style={{ color: '#fa8c16' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="涉及仓库"
              value={overview.repo_count || 0}
              prefix={<DatabaseOutlined style={{ color: '#722ed1' }} />}
            />
          </Card>
        </Col>
      </Row>

      {/* 文件大小统计 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic
              title="已下载文件总大小"
              value={formatFileSize(overview.total_size)}
              prefix={<HddOutlined style={{ color: '#13c2c2' }} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card size="small">
            <Statistic
              title="今日成功数"
              value={overview.today_success || 0}
              prefix={<CloudDownloadOutlined style={{ color: '#52c41a' }} />}
            />
          </Card>
        </Col>
      </Row>

      {/* 优化建议 */}
      <Card title="下载优化建议" style={{ marginBottom: 24 }}>
        {suggestions.length ? (
          <List
            size="small"
            dataSource={suggestions}
            renderItem={(item: any) => {
              const config = severityConfig[item.severity] || { color: 'default', text: item.severity || '-' }
              return (
                <List.Item>
                  <List.Item.Meta
                    title={(
                      <Space>
                        <Tag color={config.color}>{config.text}</Tag>
                        <span>{item.title}</span>
                      </Space>
                    )}
                    description={`${item.reason || '-'}；建议：${item.action || '-'}`}
                  />
                </List.Item>
              )
            }}
          />
        ) : (
          <Alert
            type="success"
            showIcon
            message="暂无高风险建议"
            description="近7日各仓库下载成功率、失败率均在正常范围内。"
          />
        )}
      </Card>

      {/* 趋势图 + 仓库分布 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={14}>
          <Card title="近7日下载趋势">
            <LineChart data={trendChartData} color="#52c41a" height={300} />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="仓库文件分布">
            <PieChart data={repoChartData} height={300} />
          </Card>
        </Col>
      </Row>

      {/* 失败分析 + 文件类型分布 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={12}>
          <Card title="失败文件仓库分布">
            <BarChart
              data={failureData}
              color="#ff4d4f"
              height={280}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="文件类型分布">
            <BarChart
              data={fileTypeChartData}
              color="#1890ff"
              height={280}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default CrawlerStats
