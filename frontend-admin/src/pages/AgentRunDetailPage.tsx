import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  Select,
  Space,
  Spin,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  DatabaseOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'

import * as agentRunsApi from '@/api/agentRuns'
import type { AdminAgentRunEvent, AdminAgentSessionDetail, AdminAgentTurn } from '@/api/agentRuns'
import RunMemoryDrawer from './agent-observability/RunMemoryDrawer'
import './agent-observability/agent-observability.css'

const { Title, Text, Paragraph } = Typography

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

const eventTypeNames: Record<string, string> = {
  'run.created': '运行已创建',
  'run.status_changed': '运行状态变化',
  'run.completed': '运行已完成',
  'run.failed': '运行失败',
  'step.started': '步骤开始',
  'step.completed': '步骤完成',
  'step.failed': '步骤失败',
  'tool.called': '工具调用',
  'tool.result': '工具返回结果',
  'message.started': '消息生成开始',
  'message.delta': '消息内容增量',
  'message.completed': '消息生成完成',
  'message.failed': '消息生成失败',
  'artifact.rendered': '产物已生成',
  'workflow.input.required': '等待用户输入',
  'workflow.approval.required': '等待人工审批',
  error: '执行错误',
}

const getAgentEventTypeLabel = (eventType: string) =>
  `${eventTypeNames[eventType] || '未知事件'}（${eventType}）`

const eventColor = (event: AdminAgentRunEvent) => {
  if (event.event_type === 'error' || event.event_type.includes('failed')) return 'red'
  if (event.event_type.includes('completed') || event.event_type === 'tool.result') return 'green'
  return 'blue'
}

const renderJson = (value: unknown) => (
  <pre
    style={{
      margin: 0,
      fontSize: 12,
      padding: 8,
      borderRadius: 4,
      background: '#f5f5f5',
      overflow: 'auto',
      maxHeight: 320,
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
    }}
  >
    {JSON.stringify(value, null, 2)}
  </pre>
)

const TurnDetail = ({
  turn,
  selectedEventTypes,
  onInspectMemory,
  onReplay,
}: {
  turn: AdminAgentTurn
  selectedEventTypes: string[]
  onInspectMemory: (runId: string) => void
  onReplay: (runId: string) => void
}) => {
  const events = turn.events.filter(
    (event) => selectedEventTypes.length === 0 || selectedEventTypes.includes(event.event_type)
  )

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card size="small" title="本轮问答">
        <Space direction="vertical" style={{ width: '100%' }}>
          <div>
            <Text type="secondary">用户：</Text>
            <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
              {turn.user_message?.content || turn.input_message || '（无文本）'}
            </Paragraph>
          </div>
          <div>
            <Text type="secondary">Agent：</Text>
            {turn.assistant_messages.length === 0 ? (
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                （暂无回复消息）
              </Paragraph>
            ) : (
              turn.assistant_messages.map((assistantMessage) => (
                <Paragraph
                  key={assistantMessage.id}
                  type={assistantMessage.status === 'failed' ? 'danger' : undefined}
                  style={{ marginBottom: 4, whiteSpace: 'pre-wrap' }}
                >
                  {assistantMessage.content || '（空消息）'}
                </Paragraph>
              ))
            )}
          </div>
        </Space>
      </Card>

      {turn.runs.some((run) => run.safe_error_summary) && (
        <Alert
          type="error"
          showIcon
          message="本轮运行失败"
          description={turn.runs.find((run) => run.safe_error_summary)?.safe_error_summary}
        />
      )}

      <Collapse
        size="small"
        items={[
          {
            key: 'runs',
            label: `运行链路（${turn.runs.length} 个 Run）`,
            children: (
              <Space direction="vertical" style={{ width: '100%' }}>
                {turn.runs.map((run) => (
                  <Card
                    key={run.id}
                    size="small"
                    title={
                      <Space wrap>
                        <Tag color={run.parent_run_id ? 'geekblue' : 'purple'}>
                          {run.parent_run_id ? '子运行' : '根运行'}
                        </Tag>
                        <Text>{run.public_title || run.workflow_key}</Text>
                        <Tag color={statusColors[run.status] || 'default'}>
                          {statusLabels[run.status] || run.status}
                        </Tag>
                      </Space>
                    }
                    extra={
                      <Space size={2}>
                        <Button
                          size="small"
                          type="link"
                          icon={<DatabaseOutlined />}
                          onClick={() => onInspectMemory(run.id)}
                        >
                          记忆观测
                        </Button>
                        {run.id === turn.root_run_id ? (
                          <Button
                            size="small"
                            type="link"
                            icon={<PlayCircleOutlined />}
                            onClick={() => onReplay(run.id)}
                          >
                            重放本轮
                          </Button>
                        ) : null}
                      </Space>
                    }
                  >
                    <Descriptions size="small" column={2}>
                      <Descriptions.Item label="Run ID">{run.id}</Descriptions.Item>
                      <Descriptions.Item label="父 Run">
                        {run.parent_run_id || '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label="工作流">
                        {run.workflow_key}@{run.workflow_version}
                      </Descriptions.Item>
                      <Descriptions.Item label="当前步骤">
                        {run.current_step_key || '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label="模型配置">
                        {run.model_config_id || '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label="事件数">{run.event_count}</Descriptions.Item>
                    </Descriptions>
                  </Card>
                ))}
              </Space>
            ),
          },
          {
            key: 'events',
            label: `事件流（${events.length}/${turn.events.length}）`,
            children:
              events.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无匹配事件" />
              ) : (
                <Timeline
                  mode="left"
                  items={events.map((event) => ({
                    key: `${event.run_id}-${event.id}`,
                    color: eventColor(event),
                    label: dayjs(event.created_at).format('HH:mm:ss.SSS'),
                    children: (
                      <div>
                        <Space wrap style={{ marginBottom: 6 }}>
                          <Text strong>{getAgentEventTypeLabel(event.event_type)}</Text>
                          <Tag>{event.run_id.slice(0, 12)}</Tag>
                          <Text type="secondary">#{event.sequence}</Text>
                        </Space>
                        {renderJson(event.payload)}
                      </div>
                    ),
                  }))}
                />
              ),
          },
          {
            key: 'interactions',
            label: `审批与产物（${turn.approvals.length + turn.artifacts.length}）`,
            children:
              turn.approvals.length === 0 && turn.artifacts.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本轮没有审批或产物" />
              ) : (
                <Space direction="vertical" style={{ width: '100%' }}>
                  {turn.approvals.map((approval) => (
                    <Card key={approval.id} size="small" title={`审批：${approval.action_key}`}>
                      <Descriptions size="small" column={2}>
                        <Descriptions.Item label="状态">{approval.status}</Descriptions.Item>
                        <Descriptions.Item label="审批人">
                          {approval.decided_by || '-'}
                        </Descriptions.Item>
                      </Descriptions>
                      {approval.diff_ref ? renderJson(approval.diff_ref) : null}
                    </Card>
                  ))}
                  {turn.artifacts.map((artifact) => (
                    <Card key={artifact.id} size="small" title={`产物：${artifact.type}`}>
                      {renderJson(artifact.content)}
                    </Card>
                  ))}
                </Space>
              ),
          },
        ]}
      />
    </Space>
  )
}

const AgentRunDetailPage = () => {
  const navigate = useNavigate()
  const { id } = useParams() as { id: string }
  const [session, setSession] = useState<AdminAgentSessionDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedEventTypes, setSelectedEventTypes] = useState<string[]>([])
  const [memoryRunId, setMemoryRunId] = useState<string | null>(null)

  const fetchSession = useCallback(async () => {
    if (!id) return
    setLoading(true)
    try {
      const response = await agentRunsApi.getAgentRunDetail(id)
      setSession(response.data || null)
    } catch {
      setSession(null)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void fetchSession()
  }, [fetchSession])

  const eventTypeOptions = useMemo(() => {
    const eventTypes = new Set(
      session?.turns.flatMap((turn) => turn.events.map((event) => event.event_type)) || []
    )
    return [...eventTypes].sort().map((eventType) => ({
      value: eventType,
      label: getAgentEventTypeLabel(eventType),
    }))
  }, [session])

  const handleReplay = async (runId: string) => {
    try {
      const response = await agentRunsApi.replayAgentRun(runId)
      message.success(response.data?.message || `重放已启动：${response.data?.eval_run_id}`)
    } catch {
      message.error('重放请求失败')
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 64 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!session) {
    return (
      <div style={{ padding: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/agent-runs')}>
          返回列表
        </Button>
        <Empty description="会话不存在" style={{ marginTop: 48 }} />
      </div>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/agent-runs')}>
            返回列表
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => void fetchSession()}>
            刷新
          </Button>
        </Space>

        <div>
          <Title level={3} style={{ marginBottom: 4 }}>
            会话详情：{session.title}
          </Title>
          <Text type="secondary">每个折叠面板对应一次用户提问及其完整运行事件。</Text>
        </div>

        <Card title="会话信息">
          <Descriptions bordered column={2}>
            <Descriptions.Item label="Thread ID">{session.thread_id}</Descriptions.Item>
            <Descriptions.Item label="用户 ID">{session.user_id}</Descriptions.Item>
            <Descriptions.Item label="会话状态">{session.thread_status}</Descriptions.Item>
            <Descriptions.Item label="最新运行状态">
              <Tag color={statusColors[session.latest_status] || 'default'}>
                {statusLabels[session.latest_status] || session.latest_status}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="问答轮数">{session.turn_count}</Descriptions.Item>
            <Descriptions.Item label="Run 总数">{session.total_run_count}</Descriptions.Item>
            <Descriptions.Item label="事件总数">{session.event_count}</Descriptions.Item>
            <Descriptions.Item label="最后更新">
              {dayjs(session.updated_at).format('YYYY-MM-DD HH:mm:ss')}
            </Descriptions.Item>
          </Descriptions>
        </Card>

        <Card title="事件筛选">
          <Select
            mode="multiple"
            allowClear
            placeholder="按事件类型筛选（显示中文与英文原名）"
            style={{ width: '100%' }}
            value={selectedEventTypes}
            options={eventTypeOptions}
            onChange={setSelectedEventTypes}
          />
        </Card>

        {session.turns.length === 0 ? (
          <Empty description="该会话暂无问答运行" />
        ) : (
          <Collapse
            accordion
            defaultActiveKey={[String(session.turns.length)]}
            items={session.turns.map((turn) => ({
              key: String(turn.turn_number),
              label: (
                <Space wrap>
                  <Text strong>第 {turn.turn_number} 轮</Text>
                  <Tag color={statusColors[turn.status] || 'default'}>
                    {statusLabels[turn.status] || turn.status}
                  </Tag>
                  <Text>
                    {(turn.user_message?.content || turn.input_message || '无输入').slice(0, 80)}
                  </Text>
                  <Text type="secondary">
                    {dayjs(turn.created_at).format('YYYY-MM-DD HH:mm:ss')}
                  </Text>
                </Space>
              ),
              children: (
                <TurnDetail
                  turn={turn}
                  selectedEventTypes={selectedEventTypes}
                  onInspectMemory={setMemoryRunId}
                  onReplay={handleReplay}
                />
              ),
            }))}
          />
        )}
      </Space>
      <RunMemoryDrawer
        onClose={() => setMemoryRunId(null)}
        open={Boolean(memoryRunId)}
        runId={memoryRunId}
      />
    </div>
  )
}

export default AgentRunDetailPage
