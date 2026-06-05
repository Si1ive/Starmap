import { Row, Col, Card, Statistic, Spin } from 'antd'
import {
  UserOutlined,
  VideoCameraOutlined,
  ShareAltOutlined,
  MessageOutlined,
  CheckCircleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getDashboardStats, getDashboardCharts } from '@/api'
import { LineChart, PieChart, BarChart } from '@/components/Chart'
import type { DashboardStats } from '@/types'

const StatCard = ({
  title,
  value,
  icon,
  color,
  suffix,
}: {
  title: string
  value: number
  icon: React.ReactNode
  color: string
  suffix?: string
}) => (
  <Card bordered={false} style={{ borderRadius: 8 }}>
    <Statistic
      title={title}
      value={value}
      suffix={suffix}
      valueStyle={{ color, fontSize: 28, fontWeight: 'bold' }}
      prefix={<span style={{ marginRight: 12, fontSize: 24 }}>{icon}</span>}
    />
  </Card>
)

const Dashboard = () => {
  const { data: statsData, isLoading: statsLoading } = useQuery({
    queryKey: ['dashboardStats'],
    queryFn: getDashboardStats,
  })

  const { data: chartsData, isLoading: chartsLoading } = useQuery({
    queryKey: ['dashboardCharts'],
    queryFn: getDashboardCharts,
  })

  const stats: DashboardStats = statsData?.data || {
    person_count: 0,
    work_count: 0,
    relation_count: 0,
    today_chat_count: 0,
    data_completeness: 0,
    api_avg_response: 0,
  }

  const charts = chartsData?.data || {}

  if (statsLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '100px 0' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>数据看板</h2>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard
            title="艺人总数"
            value={stats.person_count}
            icon={<UserOutlined />}
            color="#1890ff"
          />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard
            title="作品总数"
            value={stats.work_count}
            icon={<VideoCameraOutlined />}
            color="#52c41a"
          />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard
            title="关系总数"
            value={stats.relation_count}
            icon={<ShareAltOutlined />}
            color="#722ed1"
          />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard
            title="今日对话"
            value={stats.today_chat_count}
            icon={<MessageOutlined />}
            color="#fa8c16"
          />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard
            title="数据完整率"
            value={stats.data_completeness}
            icon={<CheckCircleOutlined />}
            color="#13c2c2"
            suffix="%"
          />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard
            title="API响应"
            value={stats.api_avg_response}
            icon={<ThunderboltOutlined />}
            color="#eb2f96"
            suffix="ms"
          />
        </Col>
      </Row>

      {/* 图表区域 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="近7日对话趋势" bordered={false} style={{ borderRadius: 8 }}>
            {chartsLoading ? (
              <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                图表数据加载中...
              </div>
            ) : (
              <LineChart
                data={(charts.chat_trend || []) as { date: string; count: number }[]}
                title=""
                color="#1890ff"
                height={300}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="艺人分类分布" bordered={false} style={{ borderRadius: 8 }}>
            {chartsLoading ? (
              <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                图表数据加载中...
              </div>
            ) : (
              <PieChart
                data={(charts.category_distribution || []) as { name: string; value: number }[]}
                title=""
                height={300}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="热门搜索词Top10" bordered={false} style={{ borderRadius: 8 }}>
            {chartsLoading ? (
              <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                图表数据加载中...
              </div>
            ) : (
              <BarChart
                data={(charts.hot_search || []) as { name: string; value: number }[]}
                title=""
                color="#52c41a"
                height={300}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="爬虫任务状态" bordered={false} style={{ borderRadius: 8 }}>
            {chartsLoading ? (
              <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                数据加载中...
              </div>
            ) : (
              <BarChart
                data={(charts.crawler_status || []) as { name: string; value: number }[]}
                title=""
                color="#fa8c16"
                height={300}
              />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Dashboard
