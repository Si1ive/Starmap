import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table,
  Tag,
  Card,
  Space,
  Button,
  DatePicker,
  Input,
  Select,
  Typography,
  Row,
  Col,
  Statistic,
  Spin,
  message,
} from 'antd'
import { ReloadOutlined, PlayCircleOutlined, EyeOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { AdminAgentRun } from '@/api/agentRuns'
import * as agentRunsApi from '@/api/agentRuns'
import dayjs from 'dayjs'

const { RangePicker } = DatePicker
const { Search } = Input

interface RunStats {
  total: number
  running: number
  completed: number
  failed: number
  waiting: number
}

const statusColors: Record<string, string> = {
  queued: 'default',
  running: 'blue',
  completed: 'green',
  failed: 'red',
  waiting_for_user: 'orange',
}

const AgentRunsPage = () => {
  const navigate = useNavigate()
  const [runs, setRuns] = useState<AdminAgentRun[]>([])
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState<RunStats>({
    total: 0,
    running: 0,
    completed: 0,
    failed: 0,
    waiting: 0,
  })
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 20,
    total: 0,
  })
  const [filters, setFilters] = useState<{
    status?: string
    workflow_key?: string
    user_id?: string
    start_date?: string
    end_date?: string
  }>({})

  const fetchRuns = async (page = 1, pageSize = 20) => {
    setLoading(true)
    try {
      const params = {
        page,
        page_size: pageSize,
        ...filters,
      }
      const response = await agentRunsApi.getAgentRuns(params)
      setRuns(response.data?.items || [])
      setPagination({
        current: page,
        pageSize,
        total: response.data?.total || 0,
      })
    } catch (error) {
      message.error('获取 Agent Runs 失败')
    } finally {
      setLoading(false)
    }
  }

  const fetchStats = async () => {
    try {
      const response = await agentRunsApi.getAgentRunStats()
      const data = response.data || {}
      setStats({
        total: data.total || 0,
        running: data.running || 0,
        completed: data.completed || 0,
        failed: data.failed || 0,
        waiting: data.waiting_for_user || 0,
      })
    } catch {
      // 统计接口失败不阻塞主流程
    }
  }

  useEffect(() => {
    void fetchRuns()
    void fetchStats()
  }, [filters])

  const handleReplay = async (runId: string) => {
    try {
      const response = await agentRunsApi.replayAgentRun(runId)
      message.success(`重放已启动，Eval Run ID: ${response.data?.eval_run_id || 'unknown'}`)
    } catch (error) {
      message.error('重放请求失败')
    }
  }

  const columns: ColumnsType<AdminAgentRun> = [
    {
      title: 'Run ID',
      dataIndex: 'id',
      key: 'id',
      width: 200,
      render: (id: string) => <Typography.Text copyable>{{id}}</Typography.Text>,
    },
    {
      title: '工作流',
      dataIndex: 'workflow_key',
      key: 'workflow_key',
      width: 120,
      render: (key: string) => <Tag>{{key}}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => (
        <Tag color={statusColors[status] || 'default'}>{{status}}</Tag>
      ),
    },
    {
      title: '用户',
      dataIndex: 'user_id',
      key: 'user_id',
      width: 150,
    },
    {
      title: '当前步骤',
      dataIndex: 'current_step_key',
      key: 'current_step_key',
      width: 150,
      render: (key: string | null) => key || '-',
    },
    {
      title: '事件数',
      dataIndex: 'last_event_sequence',
      key: 'last_event_sequence',
      width: 80,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 180,
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/admin/agent-runs/${record.id}`)}
          >
            详情
          </Button>
          <Button
            type="link"
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={() => handleReplay(record.id)}
          >
            重放
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="agent-runs-page">
      <Typography.Title level={3}>Agent Runs 监控</Typography.Title>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={4}>
          <Card>
            <Statistic title="总计" value={stats.total} />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic title="运行中" value={stats.running} valueStyle={{ color: '#1890ff' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic title="已完成" value={stats.completed} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic title="失败" value={stats.failed} valueStyle={{ color: '#f5222d' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic title="等待用户" value={stats.waiting} valueStyle={{ color: '#faad14' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic title="队列中" value={stats.total - stats.running - stats.completed - stats.failed - stats.waiting} />
          </Card>
        </Col>
      </Row>

      {/* 筛选栏 */}
      <Card style={{ marginBottom: 24 }}>
        <Space wrap size="middle">
          <Select
            placeholder="状态筛选"
            allowClear
            style={{ width: 120 }}
            onChange={(value) => setFilters((prev) => ({ ...prev, status: value }))}
            options={[
              { label: '队列中', value: 'queued' },
              { label: '运行中', value: 'running' },
              { label: '已完成', value: 'completed' },
              { label: '失败', value: 'failed' },
              { label: '等待用户', value: 'waiting_for_user' },
            ]}
          />
          <Select
            placeholder="工作流筛选"
            allowClear
            style={{ width: 150 }}
            onChange={(value) => setFilters((prev) => ({ ...prev, workflow_key: value }))}
            options={[
              { label: 'conversation@v1', value: 'conversation@v1' },
              { label: 'explain@v1', value: 'explain@v1' },
              { label: 'validate@v1', value: 'validate@v1' },
              { label: 'grade@v1', value: 'grade@v1' },
              { label: 'plan@v1', value: 'plan@v1' },
            ]}
          />
          <Search
            placeholder="用户 ID"
            allowClear
            style={{ width: 200 }}
            onSearch={(value) => setFilters((prev) => ({ ...prev, user_id: value }))}
          />
          <RangePicker
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                setFilters((prev) => ({
                  ...prev,
                  start_date: dates[0].format('YYYY-MM-DD'),
                  end_date: dates[1].format('YYYY-MM-DD'),
                }))
              }
            }}
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              void fetchRuns(pagination.current, pagination.pageSize)
              void fetchStats()
            }}
          >
            刷新
          </Button>
        </Space>
      </Card>

      {/* 运行列表 */}
      <Card>
        <Table
          columns={columns}
          dataSource={runs}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1200 }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: pagination.total,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              void fetchRuns(page, pageSize)
            },
          }}
        />
      </Card>
    </div>
  )
}

export default AgentRunsPage
