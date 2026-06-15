import { Row, Col, Card, Statistic, Spin } from 'antd'
import {
  BookOutlined,
  FileTextOutlined,
  QuestionCircleOutlined,
  MessageOutlined,
  ReadOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getDashboardStats, getDashboardCharts } from '@/api'
import { PieChart, BarChart } from '@/components/Chart'
import type { DashboardStats } from '@/types'

const StatCard = ({
  title,
  value,
  icon,
  color,
}: {
  title: string
  value: number
  icon: React.ReactNode
  color: string
}) => (
  <Card bordered={false} style={{ borderRadius: 8 }}>
    <Statistic
      title={title}
      value={value}
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
    subject_count: 0,
    chapter_count: 0,
    knowledge_point_count: 0,
    question_count: 0,
    today_chat_count: 0,
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
      <h2 style={{ marginBottom: 24 }}>408考研学习平台 - 数据看板</h2>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard
            title="学科数量"
            value={stats.subject_count || 4}
            icon={<ReadOutlined />}
            color="#1890ff"
          />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard
            title="章节数量"
            value={stats.chapter_count || 0}
            icon={<BookOutlined />}
            color="#52c41a"
          />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard
            title="知识点数量"
            value={stats.knowledge_point_count || 0}
            icon={<FileTextOutlined />}
            color="#722ed1"
          />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard
            title="题目数量"
            value={stats.question_count || 0}
            icon={<QuestionCircleOutlined />}
            color="#fa8c16"
          />
        </Col>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <StatCard
            title="今日问答"
            value={stats.today_chat_count || 0}
            icon={<MessageOutlined />}
            color="#13c2c2"
          />
        </Col>
      </Row>

      {/* 图表区域 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="各学科知识点分布" bordered={false} style={{ borderRadius: 8 }}>
            {chartsLoading ? (
              <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                图表数据加载中...
              </div>
            ) : (
              <PieChart
                data={(charts.subject_distribution || []) as { name: string; value: number }[]}
                title=""
                height={300}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="知识点难度分布" bordered={false} style={{ borderRadius: 8 }}>
            {chartsLoading ? (
              <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                图表数据加载中...
              </div>
            ) : (
              <BarChart
                data={(charts.difficulty_distribution || []) as { name: string; value: number }[]}
                title=""
                color="#722ed1"
                height={300}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="题目类型分布" bordered={false} style={{ borderRadius: 8 }}>
            {chartsLoading ? (
              <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                图表数据加载中...
              </div>
            ) : (
              <PieChart
                data={(charts.question_type_distribution || []) as { name: string; value: number }[]}
                title=""
                height={300}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="快速入口" bordered={false} style={{ borderRadius: 8 }}>
            <div style={{ padding: 20 }}>
              <Row gutter={[16, 16]}>
                <Col span={12}>
                  <Card
                    hoverable
                    style={{ textAlign: 'center' }}
                    onClick={() => window.location.href = '/admin/knowledge'}
                  >
                    <BookOutlined style={{ fontSize: 32, color: '#1890ff', marginBottom: 8 }} />
                    <div>知识点管理</div>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card
                    hoverable
                    style={{ textAlign: 'center' }}
                    onClick={() => window.location.href = '/admin/questions'}
                  >
                    <QuestionCircleOutlined style={{ fontSize: 32, color: '#52c41a', marginBottom: 8 }} />
                    <div>题目管理</div>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card
                    hoverable
                    style={{ textAlign: 'center' }}
                    onClick={() => window.location.href = '/admin/conversations'}
                  >
                    <MessageOutlined style={{ fontSize: 32, color: '#722ed1', marginBottom: 8 }} />
                    <div>智能问答</div>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card
                    hoverable
                    style={{ textAlign: 'center' }}
                    onClick={() => window.location.href = '/admin/corpus'}
                  >
                    <FileTextOutlined style={{ fontSize: 32, color: '#fa8c16', marginBottom: 8 }} />
                    <div>语料入库</div>
                  </Card>
                </Col>
              </Row>
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Dashboard
