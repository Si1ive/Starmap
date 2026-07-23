import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Card,
  Descriptions,
  Tag,
  Button,
  Space,
  Timeline,
  Spin,
  Typography,
  message,
  Empty,
} from 'antd'
import { ArrowLeftOutlined, CheckCircleOutlined, CloseCircleOutlined, PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import * as agentRunsApi from '@/api/agentRuns'
import type { AdminAgentRun, AdminAgentRunEvent, AdminAgentRunApproval } from '@/api/agentRuns'

const { Title } = Typography

const statusColors: Record<string, string> = {
  queued: 'default',
  running: 'blue',
  completed: 'green',
  failed: 'red',
  waiting_for_user: 'orange',
  waiting_for_approval: 'purple',
}

const AgentRunDetailPage = () => {
  const navigate = useNavigate()
  const { id } = useParams() as { id: string }
  const [run, setRun] = useState<AdminAgentRun | null>(null)
  const [events, setEvents] = useState<AdminAgentRunEvent[]>([])
  const [approvals, setApprovals] = useState<AdminAgentRunApproval[]>([])
  const [loading, setLoading] = useState(false)
  const [eventsLoading, setEventsLoading] = useState(false)
  const [approvalsLoading, setApprovalsLoading] = useState(false)

  const fetchRun = async () => {
    if (!id) return
    setLoading(true)
    try {
      const response = await agentRunsApi.getAgentRunDetail(id)
      setRun(response.data || null)
    } catch (error) {
      message.error('获取 Run 详情失败')
    } finally {
      setLoading(false)
    }
  }

  const fetchEvents = async () => {
    if (!id) return
    setEventsLoading(true)
    try {
      const response = await agentRunsApi.getAgentRunEvents(id)
      setEvents(response.data?.events || [])
    } catch (error) {
      message.error('获取事件失败')
    } finally {
      setEventsLoading(false)
    }
  }

  const fetchApprovals = async () => {
    if (!id) return
    setApprovalsLoading(true)
    try {
      const response = await agentRunsApi.getAgentRunApprovals(id)
      setApprovals(response.data?.approvals || [])
    } catch {
      // 审批接口失败不阻塞主流程
    } finally {
      setApprovalsLoading(false)
    }
  }

  const handleReplay = async () => {
    if (!id) return
    try {
      const response = await agentRunsApi.replayAgentRun(id)
      message.success(`重放已启动，Eval Run ID: ${response.data?.eval_run_id || 'unknown'}`)
    } catch (error) {
      message.error('重放请求失败')
    }
  }

  const handleApprove = async (approvalId: string) => {
    if (!id) return
    try {
      const response = await agentRunsApi.approveApproval(id, approvalId)
      message.success(response.data?.message || '已批准')
      void fetchApprovals()
      void fetchRun()
    } catch {
      message.error('审批失败')
    }
  }

  const handleReject = async (approvalId: string) => {
    if (!id) return
    try {
      const response = await agentRunsApi.rejectApproval(id, approvalId)
      message.success(response.data?.message || '已拒绝')
      void fetchApprovals()
      void fetchRun()
    } catch {
      message.error('拒绝失败')
    }
  }

  useEffect(() => {
    void fetchRun()
    void fetchEvents()
    void fetchApprovals()
  }, [id])

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 64 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!run) {
    return (
      <div style={{ padding: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/agent-runs')}>
          返回列表
        </Button>
        <Empty description="Run 不存在" style={{ marginTop: 48 }} />
      </div>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* 头部 */}
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/agent-runs')}>
            返回列表
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => { void fetchRun(); void fetchEvents(); }}>
            刷新
          </Button>
          <Button icon={<PlayCircleOutlined />} type="primary" onClick={handleReplay}>
            重放
          </Button>
        </Space>

        <Title level={3}>Run 详情</Title>

        {/* 基本信息 */}
        <Card title="基本信息">
          <Descriptions bordered column={2}>
            <Descriptions.Item label="Run ID">{run.id}</Descriptions.Item>
            <Descriptions.Item label="Thread ID">{run.thread_id}</Descriptions.Item>
            <Descriptions.Item label="用户 ID">{run.user_id}</Descriptions.Item>
            <Descriptions.Item label="工作流">
              <Tag>{run.workflow_key}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="版本">{run.workflow_version}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={statusColors[run.status] || 'default'}>{run.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="当前步骤">{run.current_step_key || '-'}</Descriptions.Item>
            <Descriptions.Item label="事件数">{run.last_event_sequence}</Descriptions.Item>
            <Descriptions.Item label="Lease Owner">{run.lease_owner || '-'}</Descriptions.Item>
            <Descriptions.Item label="Lease Expires">{run.lease_expires_at ? dayjs(run.lease_expires_at).format('YYYY-MM-DD HH:mm:ss') : '-'}</Descriptions.Item>
            <Descriptions.Item label="创建时间">{dayjs(run.created_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
            <Descriptions.Item label="更新时间">{dayjs(run.updated_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
          </Descriptions>
        </Card>

        {/* 错误信息 */}
        {run.safe_error_summary && (
          <Card title="错误摘要" style={{ borderColor: '#ff4d4f' }}>
            <Typography.Text type="danger">{run.safe_error_summary}</Typography.Text>
          </Card>
        )}

        {/* 审批请求 */}
        {run.status === 'waiting_for_approval' && (
          <Card
            title="审批请求"
            extra={
              <Button icon={<ReloadOutlined />} onClick={fetchApprovals}>
                刷新
              </Button>
            }
          >
            <Spin spinning={approvalsLoading}>
              {approvals.length === 0 ? (
                <Empty description="暂无审批请求" />
              ) : (
                <Space direction="vertical" style={{ width: '100%' }}>
                  {approvals.map((approval) => (
                    <Card
                      key={approval.id}
                      size="small"
                      title={
                        <Space>
                          <Tag color={approval.status === 'pending' ? 'blue' : approval.status === 'approved' ? 'green' : 'red'}>
                            {approval.status}
                          </Tag>
                          <span>{approval.action_key}</span>
                        </Space>
                      }
                      extra={
                        approval.status === 'pending' ? (
                          <Space>
                            <Button
                              size="small"
                              danger
                              icon={<CloseCircleOutlined />}
                              onClick={() => handleReject(approval.id)}
                            >
                              拒绝
                            </Button>
                            <Button
                              size="small"
                              type="primary"
                              icon={<CheckCircleOutlined />}
                              onClick={() => handleApprove(approval.id)}
                            >
                              批准
                            </Button>
                          </Space>
                        ) : null
                      }
                    >
                      <Descriptions size="small" column={1}>
                        <Descriptions.Item label="审批 ID">{approval.id}</Descriptions.Item>
                        {approval.diff_ref && (
                          <Descriptions.Item label="变更内容">
                            <pre style={{ fontSize: 12, background: '#f5f5f5', padding: 8, borderRadius: 4, maxHeight: 200, overflow: 'auto' }}>
                              {(() => {
                                try {
                                  const diff = JSON.parse(approval.diff_ref)
                                  return JSON.stringify(diff, null, 2)
                                } catch {
                                  return approval.diff_ref
                                }
                              })()}
                            </pre>
                          </Descriptions.Item>
                        )}
                        {approval.expires_at && (
                          <Descriptions.Item label="过期时间">
                            {dayjs(approval.expires_at).format('YYYY-MM-DD HH:mm:ss')}
                          </Descriptions.Item>
                        )}
                        {approval.decided_by && (
                          <Descriptions.Item label="审批人">{approval.decided_by}</Descriptions.Item>
                        )}
                      </Descriptions>
                    </Card>
                  ))}
                </Space>
              )}
            </Spin>
          </Card>
        )}

        {/* 事件流 */}
        <Card
          title="事件流"
          extra={
            <Button icon={<ReloadOutlined />} onClick={fetchEvents}>
              刷新
            </Button>
          }
        >
          <Spin spinning={eventsLoading}>
            {events.length === 0 ? (
              <Empty description="暂无事件" />
            ) : (
              <Timeline mode="left">
                {events.map((event) => (
                  <Timeline.Item
                    key={event.id}
                    label={dayjs(event.created_at).format('HH:mm:ss')}
                    color={
                      event.event_type === 'error'
                        ? 'red'
                        : event.event_type.includes('completed')
                          ? 'green'
                          : 'blue'
                    }
                  >
                    <div>
                      <strong>{event.event_type}</strong>
                      <pre style={{ marginTop: 4, fontSize: 12, background: '#f5f5f5', padding: 8, borderRadius: 4 }}>
                        {JSON.stringify(event.payload, null, 2)}
                      </pre>
                    </div>
                  </Timeline.Item>
                ))}
              </Timeline>
            )}
          </Spin>
        </Card>
      </Space>
    </div>
  )
}

export default AgentRunDetailPage
