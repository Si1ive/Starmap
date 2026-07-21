import { Button, Spin } from 'antd'
import {
  ArrowRightOutlined,
  BookOutlined,
  FileTextOutlined,
  MessageOutlined,
  QuestionCircleOutlined,
  ReadOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getDashboardCharts, getDashboardStats } from '@/api'
import { BarChart, PieChart } from '@/components/Chart'
import PageHeader from '@/components/PageHeader'
import type { DashboardStats } from '@/types'

type MetricTone = 'blue' | 'jade' | 'amber' | 'red' | 'neutral'

interface DashboardMetricProps {
  title: string
  value: number
  icon: React.ReactNode
  tone: MetricTone
  detail: string
}

const DashboardMetric = ({
  title,
  value,
  icon,
  tone,
  detail,
}: DashboardMetricProps) => (
  <div className={`dashboard-metric dashboard-metric--${tone}`}>
    <span className="dashboard-metric__icon">{icon}</span>
    <span className="dashboard-metric__copy">
      <small>{title}</small>
      <strong>{value.toLocaleString('zh-CN')}</strong>
      <em>{detail}</em>
    </span>
  </div>
)

const quickActions = [
  {
    icon: <BookOutlined />,
    title: '知识点管理',
    detail: '检查知识结构、状态与来源',
    route: '/admin/knowledge',
  },
  {
    icon: <QuestionCircleOutlined />,
    title: '题目管理',
    detail: '维护题干、答案与审核状态',
    route: '/admin/questions',
  },
  {
    icon: <MessageOutlined />,
    title: '智能问答',
    detail: '查看对话内容与引用证据',
    route: '/admin/conversations',
  },
  {
    icon: <FileTextOutlined />,
    title: '语料管理',
    detail: '跟进文档解析和内容入库',
    route: '/admin/corpus',
  },
]

const Dashboard = () => {
  const navigate = useNavigate()
  const {
    data: statsData,
    isLoading: statsLoading,
    isFetching: statsFetching,
    refetch: refetchStats,
  } = useQuery({
    queryKey: ['dashboardStats'],
    queryFn: getDashboardStats,
  })

  const {
    data: chartsData,
    isLoading: chartsLoading,
    isFetching: chartsFetching,
    refetch: refetchCharts,
  } = useQuery({
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
  const refreshing = statsFetching || chartsFetching

  const refreshDashboard = () => {
    void Promise.all([refetchStats(), refetchCharts()])
  }

  if (statsLoading) {
    return (
      <div className="admin-page-loading">
        <Spin size="large" tip="正在读取运行概览" />
      </div>
    )
  }

  return (
    <div className="dashboard-page">
      <PageHeader
        eyebrow="运行概览"
        title="数据看板"
        description="查看内容资产规模、题目结构和今日问答活动。"
        actions={
          <Button
            icon={<ReloadOutlined />}
            loading={refreshing}
            onClick={refreshDashboard}
          >
            刷新数据
          </Button>
        }
      />

      <section className="dashboard-metrics" aria-label="核心指标">
        <DashboardMetric
          title="学科"
          value={stats.subject_count || 4}
          icon={<ReadOutlined />}
          tone="blue"
          detail="408 核心范围"
        />
        <DashboardMetric
          title="章节"
          value={stats.chapter_count || 0}
          icon={<BookOutlined />}
          tone="jade"
          detail="大纲结构节点"
        />
        <DashboardMetric
          title="知识点"
          value={stats.knowledge_point_count || 0}
          icon={<FileTextOutlined />}
          tone="neutral"
          detail="可检索内容资产"
        />
        <DashboardMetric
          title="题目"
          value={stats.question_count || 0}
          icon={<QuestionCircleOutlined />}
          tone="amber"
          detail="已入库题目总量"
        />
        <DashboardMetric
          title="今日问答"
          value={stats.today_chat_count || 0}
          icon={<MessageOutlined />}
          tone="red"
          detail="当日对话活动"
        />
      </section>

      <section className="dashboard-grid">
        <article className="dashboard-panel">
          <header className="dashboard-panel__header">
            <div>
              <h2>各学科知识点分布</h2>
              <p>观察内容资产在四个学科之间的覆盖情况。</p>
            </div>
            <span>知识资产</span>
          </header>
          <div className="dashboard-panel__chart">
            {chartsLoading ? (
              <div className="dashboard-chart-loading">图表数据加载中</div>
            ) : (
              <PieChart
                data={(charts.subject_distribution || []) as { name: string; value: number }[]}
                height={280}
              />
            )}
          </div>
        </article>

        <article className="dashboard-panel">
          <header className="dashboard-panel__header">
            <div>
              <h2>知识点难度分布</h2>
              <p>用于发现难度标注是否出现结构性偏移。</p>
            </div>
            <span>难度标注</span>
          </header>
          <div className="dashboard-panel__chart">
            {chartsLoading ? (
              <div className="dashboard-chart-loading">图表数据加载中</div>
            ) : (
              <BarChart
                data={(charts.difficulty_distribution || []) as { name: string; value: number }[]}
                color="#31594e"
                height={280}
              />
            )}
          </div>
        </article>

        <article className="dashboard-panel">
          <header className="dashboard-panel__header">
            <div>
              <h2>题目类型分布</h2>
              <p>对比客观题与综合题的库存构成。</p>
            </div>
            <span>题库结构</span>
          </header>
          <div className="dashboard-panel__chart">
            {chartsLoading ? (
              <div className="dashboard-chart-loading">图表数据加载中</div>
            ) : (
              <PieChart
                data={(charts.question_type_distribution || []) as { name: string; value: number }[]}
                height={260}
              />
            )}
          </div>
        </article>

        <article className="dashboard-panel dashboard-quick-actions">
          <header className="dashboard-panel__header">
            <div>
              <h2>常用操作</h2>
              <p>直接进入高频内容治理流程。</p>
            </div>
            <span>工作入口</span>
          </header>
          <div className="dashboard-quick-actions__list">
            {quickActions.map((action) => (
              <button key={action.route} onClick={() => navigate(action.route)} type="button">
                <span className="dashboard-quick-actions__icon">{action.icon}</span>
                <span>
                  <strong>{action.title}</strong>
                  <small>{action.detail}</small>
                </span>
                <ArrowRightOutlined />
              </button>
            ))}
          </div>
        </article>
      </section>
    </div>
  )
}

export default Dashboard
