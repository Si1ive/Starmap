import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button,
  Card,
  Col,
  DatePicker,
  Input,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tabs,
  Typography,
  message,
} from 'antd'
import { EyeOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'

import * as agentRunsApi from '@/api/agentRuns'
import type { AdminAgentSession } from '@/api/agentRuns'
import MemoryOutboxPanel from './agent-observability/MemoryOutboxPanel'
import './agent-observability/agent-observability.css'

const { RangePicker } = DatePicker
const { Search } = Input

interface SessionStats {
  total: number
  running: number
  completed: number
  failed: number
  waiting_for_user: number
  waiting_for_approval: number
}

const statusColors: Record<string, string> = {
  queued: 'default',
  running: 'blue',
  completed: 'green',
  failed: 'red',
  waiting_for_user: 'orange',
  waiting_for_approval: 'purple',
}

const statusLabels: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  waiting_for_user: '等待用户',
  waiting_for_approval: '等待审批',
}

const AgentRunsPage = () => {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<AdminAgentSession[]>([])
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState<SessionStats>({
    total: 0,
    running: 0,
    completed: 0,
    failed: 0,
    waiting_for_user: 0,
    waiting_for_approval: 0,
  })
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [filters, setFilters] = useState<{
    status?: string
    workflow_key?: string
    user_id?: string
    start_date?: string
    end_date?: string
  }>({})

  const fetchSessions = useCallback(
    async (page = 1, pageSize = 20) => {
      setLoading(true)
      try {
        const response = await agentRunsApi.getAgentRuns({
          page,
          page_size: pageSize,
          ...filters,
        })
        setSessions(response.data?.items || [])
        setPagination({
          current: page,
          pageSize,
          total: response.data?.total || 0,
        })
      } catch {
        message.error('获取 Agent 会话监控失败')
      } finally {
        setLoading(false)
      }
    },
    [filters]
  )

  const fetchStats = useCallback(async () => {
    try {
      const response = await agentRunsApi.getAgentRunStats()
      const data = response.data || {}
      setStats({
        total: Number(data.total) || 0,
        running: Number(data.running) || 0,
        completed: Number(data.completed) || 0,
        failed: Number(data.failed) || 0,
        waiting_for_user: Number(data.waiting_for_user) || 0,
        waiting_for_approval: Number(data.waiting_for_approval) || 0,
      })
    } catch {
      // 统计接口失败不阻塞会话列表。
    }
  }, [])

  useEffect(() => {
    void fetchSessions()
    void fetchStats()
  }, [fetchSessions, fetchStats])

  const columns: ColumnsType<AdminAgentSession> = [
    {
      title: '会话',
      dataIndex: 'title',
      key: 'title',
      width: 260,
      render: (title: string, record) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{title}</Typography.Text>
          <Typography.Text type="secondary" copyable style={{ fontSize: 12 }}>
            {record.thread_id}
          </Typography.Text>
        </Space>
      ),
    },
    { title: '用户 ID', dataIndex: 'user_id', key: 'user_id', width: 180 },
    {
      title: '最新状态',
      dataIndex: 'latest_status',
      key: 'latest_status',
      width: 120,
      render: (status: string) => (
        <Tag color={statusColors[status] || 'default'}>{statusLabels[status] || status}</Tag>
      ),
    },
    { title: '问答轮数', dataIndex: 'turn_count', key: 'turn_count', width: 100 },
    { title: '运行节点', dataIndex: 'total_run_count', key: 'total_run_count', width: 100 },
    { title: '事件数', dataIndex: 'event_count', key: 'event_count', width: 90 },
    {
      title: '最新工作流',
      dataIndex: 'latest_workflow_key',
      key: 'latest_workflow_key',
      width: 140,
      render: (value: string | null) => value || '-',
    },
    {
      title: '最后更新',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
      render: (date: string) => dayjs(date).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 90,
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => navigate(`/admin/agent-runs/${record.thread_id}`)}
        >
          详情
        </Button>
      ),
    },
  ]

  return (
    <div className="agent-runs-page">
      <Typography.Title level={3}>Agent 会话监控</Typography.Title>
      <Typography.Paragraph type="secondary">
        一条记录对应一个完整会话；详情中按用户提问分组展示多轮运行与事件。
      </Typography.Paragraph>

      <Tabs
        className="agent-observability-tabs"
        items={[
          {
            key: 'sessions',
            label: '会话与 Run',
            children: (
              <>
                <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
                  <Col span={4}>
                    <Card>
                      <Statistic title="会话总计" value={stats.total} />
                    </Card>
                  </Col>
                  <Col span={4}>
                    <Card>
                      <Statistic
                        title="运行中"
                        value={stats.running}
                        valueStyle={{ color: '#1890ff' }}
                      />
                    </Card>
                  </Col>
                  <Col span={4}>
                    <Card>
                      <Statistic
                        title="已完成"
                        value={stats.completed}
                        valueStyle={{ color: '#52c41a' }}
                      />
                    </Card>
                  </Col>
                  <Col span={4}>
                    <Card>
                      <Statistic
                        title="失败"
                        value={stats.failed}
                        valueStyle={{ color: '#f5222d' }}
                      />
                    </Card>
                  </Col>
                  <Col span={4}>
                    <Card>
                      <Statistic
                        title="等待用户"
                        value={stats.waiting_for_user}
                        valueStyle={{ color: '#faad14' }}
                      />
                    </Card>
                  </Col>
                  <Col span={4}>
                    <Card>
                      <Statistic
                        title="等待审批"
                        value={stats.waiting_for_approval}
                        valueStyle={{ color: '#722ed1' }}
                      />
                    </Card>
                  </Col>
                </Row>

                <Card style={{ marginBottom: 24 }}>
                  <Space wrap size="middle">
                    <Select
                      placeholder="会话中运行状态"
                      allowClear
                      style={{ width: 160 }}
                      onChange={(value) =>
                        setFilters((previous) => ({ ...previous, status: value }))
                      }
                      options={Object.entries(statusLabels).map(([value, label]) => ({
                        value,
                        label,
                      }))}
                    />
                    <Select
                      placeholder="工作流筛选"
                      allowClear
                      style={{ width: 150 }}
                      onChange={(value) =>
                        setFilters((previous) => ({ ...previous, workflow_key: value }))
                      }
                      options={[
                        { label: 'conversation', value: 'conversation' },
                        { label: 'explain', value: 'explain' },
                        { label: 'validate', value: 'validate' },
                        { label: 'grade', value: 'grade' },
                        { label: 'plan', value: 'plan' },
                      ]}
                    />
                    <Search
                      placeholder="用户 ID"
                      allowClear
                      style={{ width: 200 }}
                      onSearch={(value) =>
                        setFilters((previous) => ({ ...previous, user_id: value || undefined }))
                      }
                    />
                    <RangePicker
                      onChange={(dates) =>
                        setFilters((previous) => ({
                          ...previous,
                          start_date: dates?.[0]?.format('YYYY-MM-DD'),
                          end_date: dates?.[1]?.format('YYYY-MM-DD'),
                        }))
                      }
                    />
                    <Button
                      icon={<ReloadOutlined />}
                      onClick={() => {
                        void fetchSessions(pagination.current, pagination.pageSize)
                        void fetchStats()
                      }}
                    >
                      刷新
                    </Button>
                  </Space>
                </Card>

                <Card>
                  <Table
                    columns={columns}
                    dataSource={sessions}
                    rowKey="thread_id"
                    loading={loading}
                    scroll={{ x: 1300 }}
                    pagination={{
                      current: pagination.current,
                      pageSize: pagination.pageSize,
                      total: pagination.total,
                      showSizeChanger: true,
                      showTotal: (total) => `共 ${total} 个会话`,
                      onChange: (page, pageSize) => void fetchSessions(page, pageSize),
                    }}
                  />
                </Card>
              </>
            ),
          },
          {
            key: 'memory-outbox',
            label: '记忆派生任务',
            children: <MemoryOutboxPanel />,
          },
        ]}
      />
    </div>
  )
}

export default AgentRunsPage
