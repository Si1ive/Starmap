import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import {
  ArrowDownOutlined,
  ArrowLeftOutlined,
  BranchesOutlined,
  DatabaseOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'

import * as agentRunsApi from '@/api/agentRuns'
import type {
  AdminAgentRun,
  AdminAgentRunEvent,
  AdminAgentSessionDetail,
  AdminAgentTurn,
} from '@/api/agentRuns'
import PlainDataBlock from './agent-observability/PlainDataBlock'
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

const nodeLabels: Record<string, string> = {
  route: '理解请求并选择工作流',
  dispatch_workflow: '创建业务子运行',
  direct_answer: '直接生成回答',
  load_learning_evidence: '读取练习主题与约束',
  question_discovery: '在题库中查找候选题',
  question_gate: '检查候选题资格',
  generate_question: '模型生成练习题',
  composition_gate: '整理题型与难度',
  create_draft: '生成练习草稿',
  render_artifact: '渲染最终产物',
  completed: '完成运行',
  load_scope: '读取本轮上下文',
  evidence_loop: '检索讲解资料',
  evidence_gate: '检查资料是否可用',
  generate_explanation: '生成讲解',
  citation_gate: '检查引用',
  load_attempt_snapshot: '读取题目与作答',
  objective_grade: '确定性判分',
  rubric_gate: '检查评分证据',
  generate_feedback: '生成反馈',
  feedback_gate: '检查反馈',
  aggregate_learning_evidence: '汇总学习证据',
  planning_precondition_gate: '检查计划条件',
  propose_plan_delta: '生成计划草案',
  plan_quality_gate: '检查计划质量',
  create_approval: '创建审批',
  wait_for_approval: '等待审批',
  apply_plan_change: '应用已批准计划',
  render_plan_result: '渲染计划结果',
}

const eventLabels: Record<string, string> = {
  'tool.called': '工具调用参数',
  'tool.result': '工具返回结果',
  'workflow.input.required': '等待用户补充信息',
  'workflow.approval.required': '等待人工审批',
  'artifact.rendered': '产物已保存',
  'message.completed': '回复已保存',
  'message.failed': '回复生成失败',
}

interface FlowStep {
  stepId: string
  nodeName: string
  nodeType: string
  startedAt: string
  completedAt: string | null
  input: unknown
  output: unknown
  error: string | null
  waiting: boolean
  degraded: boolean
  relatedEvents: AdminAgentRunEvent[]
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}

function buildFlowSteps(events: AdminAgentRunEvent[]): FlowStep[] {
  const steps: FlowStep[] = []
  const byId = new Map<string, FlowStep>()
  let current: FlowStep | null = null

  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    const payload = asRecord(event.payload)
    const stepId = String(payload.step_id || '')
    if (event.event_type === 'step.started' && stepId) {
      current = {
        stepId,
        nodeName: String(payload.node_name || 'unknown'),
        nodeType: String(payload.node_type || 'action'),
        startedAt: event.created_at,
        completedAt: null,
        input: payload.input || {},
        output: {},
        error: null,
        waiting: false,
        degraded: false,
        relatedEvents: [],
      }
      steps.push(current)
      byId.set(stepId, current)
      continue
    }

    if ((event.event_type === 'step.completed' || event.event_type === 'step.failed') && stepId) {
      const step = byId.get(stepId)
      if (step) {
        step.completedAt = event.created_at
        step.output = payload.output || {}
        step.error = event.event_type === 'step.failed' ? String(payload.error || '步骤失败') : null
        step.waiting = Boolean(payload.waiting)
        const output = asRecord(payload.output)
        step.degraded = Boolean(output.fallback || output.notice || output.gate_passed === false)
        if (current?.stepId === stepId) current = null
      }
      continue
    }

    if (current && event.event_type !== 'message.delta') {
      current.relatedEvents.push(event)
    }
  }
  return steps
}

const stepTone = (step: FlowStep) => {
  if (step.error) return 'failed'
  if (step.waiting) return 'waiting'
  if (step.degraded) return 'degraded'
  if (!step.completedAt) return 'running'
  return 'completed'
}

const stepStatusLabel = (step: FlowStep) => {
  if (step.error) return '失败'
  if (step.waiting) return '等待输入'
  if (step.degraded) return '已降级继续'
  if (!step.completedAt) return '执行中'
  return '完成'
}

function EventEvidence({ event }: { event: AdminAgentRunEvent }) {
  return (
    <div className="run-flow-event">
      <div className="run-flow-event__heading">
        <Text strong>{eventLabels[event.event_type] || '运行事件'}</Text>
        <Text type="secondary">{dayjs(event.created_at).format('HH:mm:ss.SSS')}</Text>
      </div>
      <PlainDataBlock value={event.payload} maxHeight={240} />
    </div>
  )
}

function StepNode({ step, index }: { step: FlowStep; index: number }) {
  const tone = stepTone(step)
  const detailItems = [
    {
      key: 'io',
      label: `查看输入、输出与调用证据（${step.relatedEvents.length}）`,
      children: (
        <div className="run-flow-io-grid">
          <div>
            <Text strong>传入参数与步骤前上下文</Text>
            <PlainDataBlock value={step.input} maxHeight={320} />
          </div>
          <div>
            <Text strong>步骤输出与分支依据</Text>
            <PlainDataBlock
              value={step.error ? { error: step.error } : step.output}
              maxHeight={320}
            />
          </div>
          {step.relatedEvents.length ? (
            <div className="run-flow-evidence">
              <Text strong>步骤内的工具、交互与落库事件</Text>
              {step.relatedEvents.map((event) => (
                <EventEvidence event={event} key={`${event.run_id}-${event.id}`} />
              ))}
            </div>
          ) : null}
        </div>
      ),
    },
  ]

  return (
    <div className={`run-flow-step is-${tone}`}>
      <div className="run-flow-step__rail" aria-hidden="true">
        <span>{index + 1}</span>
      </div>
      <div className="run-flow-step__body">
        <div className="run-flow-step__heading">
          <div>
            <Text strong>{nodeLabels[step.nodeName] || step.nodeName}</Text>
            <Text className="run-flow-step__technical" type="secondary">
              {step.nodeName} · {step.nodeType}
            </Text>
          </div>
          <Space wrap size={8}>
            <Tag className={`run-flow-status is-${tone}`}>{stepStatusLabel(step)}</Tag>
            <Text type="secondary">
              {dayjs(step.startedAt).format('HH:mm:ss.SSS')}
              {step.completedAt ? ` → ${dayjs(step.completedAt).format('HH:mm:ss.SSS')}` : ''}
            </Text>
          </Space>
        </div>
        {step.degraded ? (
          <Alert
            message="这一步没有阻塞运行，已按降级分支继续"
            description={String(asRecord(step.output).notice || '查看步骤输出可确认分支原因。')}
            showIcon
            type="warning"
          />
        ) : null}
        {step.error ? <Alert message={step.error} showIcon type="error" /> : null}
        <Collapse ghost items={detailItems} size="small" />
      </div>
    </div>
  )
}

function RunLane({ run, events }: { run: AdminAgentRun; events: AdminAgentRunEvent[] }) {
  const steps = useMemo(() => buildFlowSteps(events), [events])
  return (
    <section className={`run-flow-lane is-${run.status}`}>
      <div className="run-flow-lane__header">
        <div>
          <Space wrap size={8}>
            <Tag color={run.parent_run_id ? 'geekblue' : 'purple'}>
              {run.parent_run_id ? '业务子运行' : '路由根运行'}
            </Tag>
            <Title level={5}>{run.public_title || run.workflow_key}</Title>
            <Tag color={statusColors[run.status] || 'default'}>
              {statusLabels[run.status] || run.status}
            </Tag>
          </Space>
          <Text type="secondary">
            {run.workflow_key}@{run.workflow_version} · {run.id}
          </Text>
        </div>
      </div>

      <div className="run-flow-entry">
        <BranchesOutlined />
        <div>
          <Text strong>运行入口</Text>
          <Paragraph>{run.input_message || '没有单独的文本输入'}</Paragraph>
          <Space wrap size={6}>
            <Tag>模型配置：{run.model_config_id || '继承系统配置'}</Tag>
            {run.parent_run_id ? <Tag>父 Run：{run.parent_run_id}</Tag> : null}
          </Space>
        </div>
      </div>

      {steps.length ? (
        <div className="run-flow-steps">
          {steps.map((step, index) => (
            <StepNode index={index} key={step.stepId} step={step} />
          ))}
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该 Run 还没有步骤事件" />
      )}
    </section>
  )
}

function TurnFlow({ turn }: { turn: AdminAgentTurn }) {
  const orderedRuns = [...turn.runs].sort((a, b) => {
    if (a.id === turn.root_run_id) return -1
    if (b.id === turn.root_run_id) return 1
    return a.created_at.localeCompare(b.created_at)
  })

  return (
    <div className="turn-flow">
      <div className="turn-flow__conversation">
        <div>
          <Text type="secondary">用户输入</Text>
          <Paragraph>{turn.user_message?.content || turn.input_message || '（无文本）'}</Paragraph>
        </div>
        <ArrowDownOutlined aria-hidden="true" />
        <div>
          <Text type="secondary">最终回复</Text>
          {turn.assistant_messages.length ? (
            turn.assistant_messages.map((item) => (
              <Paragraph key={item.id} type={item.status === 'failed' ? 'danger' : undefined}>
                {item.content || '（空消息）'}
              </Paragraph>
            ))
          ) : (
            <Paragraph type="secondary">尚未生成回复</Paragraph>
          )}
        </div>
      </div>

      {orderedRuns.some((run) => run.safe_error_summary) ? (
        <Alert
          description={orderedRuns.find((run) => run.safe_error_summary)?.safe_error_summary}
          message="本轮存在真实失败"
          showIcon
          type="error"
        />
      ) : null}

      <div className="run-flow-map">
        {orderedRuns.map((run, index) => (
          <div key={run.id}>
            {index ? (
              <div className="run-flow-handoff">
                <ArrowDownOutlined />
                <span>父运行把冻结上下文与独立请求交给业务工作流</span>
              </div>
            ) : null}
            <RunLane events={turn.events.filter((event) => event.run_id === run.id)} run={run} />
          </div>
        ))}
      </div>

      {turn.approvals.length || turn.artifacts.length ? (
        <Collapse
          items={[
            {
              key: 'results',
              label: `本轮审批与产物（${turn.approvals.length + turn.artifacts.length}）`,
              children: (
                <div className="run-flow-result-grid">
                  {turn.approvals.map((approval) => (
                    <Card key={approval.id} size="small" title={`审批：${approval.action_key}`}>
                      <PlainDataBlock value={approval} maxHeight={260} />
                    </Card>
                  ))}
                  {turn.artifacts.map((artifact) => (
                    <Card key={artifact.id} size="small" title={`产物：${artifact.type}`}>
                      <PlainDataBlock value={artifact.content} maxHeight={320} />
                    </Card>
                  ))}
                </div>
              ),
            },
          ]}
        />
      ) : null}
    </div>
  )
}

const AgentRunDetailPage = () => {
  const navigate = useNavigate()
  const { id } = useParams() as { id: string }
  const [session, setSession] = useState<AdminAgentSessionDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [memoryOpen, setMemoryOpen] = useState(false)

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

  if (loading) {
    return (
      <div className="admin-page-loading">
        <Spin size="large" />
      </div>
    )
  }

  if (!session) {
    return (
      <div className="agent-run-detail-page">
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/agent-runs')}>
          返回列表
        </Button>
        <Empty description="会话不存在" style={{ marginTop: 48 }} />
      </div>
    )
  }

  return (
    <div className="agent-run-detail-page">
      <div className="agent-run-detail-page__toolbar">
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/agent-runs')}>
          返回列表
        </Button>
        <Button icon={<ReloadOutlined />} onClick={() => void fetchSession()}>
          刷新
        </Button>
        <Button icon={<DatabaseOutlined />} onClick={() => setMemoryOpen(true)} type="primary">
          查看上下文记忆变化
        </Button>
      </div>

      <header className="agent-run-detail-hero">
        <div>
          <Text type="secondary">Agent 执行线路图</Text>
          <Title level={3}>{session.title}</Title>
          <Paragraph>
            从用户输入开始，沿节点查看传入参数、步骤输出、分支原因、工具调用和记忆变化入口。
          </Paragraph>
        </div>
        <div className="agent-run-detail-hero__stats">
          <div>
            <span>对话轮次</span>
            <strong>{session.turn_count}</strong>
          </div>
          <div>
            <span>Run</span>
            <strong>{session.total_run_count}</strong>
          </div>
          <div>
            <span>事件</span>
            <strong>{session.event_count}</strong>
          </div>
          <div>
            <span>最新状态</span>
            <strong>{statusLabels[session.latest_status]}</strong>
          </div>
        </div>
      </header>

      <Descriptions className="agent-run-detail-meta" column={{ xs: 1, sm: 2, lg: 4 }} size="small">
        <Descriptions.Item label="Thread ID">{session.thread_id}</Descriptions.Item>
        <Descriptions.Item label="用户 ID">{session.user_id}</Descriptions.Item>
        <Descriptions.Item label="会话状态">{session.thread_status}</Descriptions.Item>
        <Descriptions.Item label="最后更新">
          {dayjs(session.updated_at).format('YYYY-MM-DD HH:mm:ss')}
        </Descriptions.Item>
      </Descriptions>

      <Card
        className="agent-run-practices"
        size="small"
        title={`会话练习（${session.practices.length}）`}
      >
        {session.practices.length ? (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            {session.practices.map((practice) => (
              <Descriptions bordered column={{ xs: 1, md: 4 }} key={practice.id} size="small">
                <Descriptions.Item label="练习">{practice.title}</Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={practice.status === 'submitted' ? 'green' : practice.status === 'active' ? 'blue' : 'gold'}>
                    {practice.status === 'submitted' ? '已完成' : practice.status === 'active' ? '进行中' : '草稿'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="题目/得分">
                  {practice.question_count} 题 · {practice.awarded_score ?? '-'}/{practice.total_score}
                </Descriptions.Item>
                <Descriptions.Item label="来源 Run">{practice.agent_run_id || '-'}</Descriptions.Item>
              </Descriptions>
            ))}
          </Space>
        ) : <Empty description="该会话尚未创建练习" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Card>

      <Card
        className="agent-run-learning-activities"
        size="small"
        title={`学习事件（${session.learning_activities.length}）`}
      >
        {session.learning_activities.length ? (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            {session.learning_activities.map((activity) => (
              <Descriptions bordered column={{ xs: 1, md: 4 }} key={activity.id} size="small">
                <Descriptions.Item label="事件">{activity.event_type}</Descriptions.Item>
                <Descriptions.Item label="主题">{activity.topic_keywords.join('、') || '-'}</Descriptions.Item>
                <Descriptions.Item label="证据层级">
                  <Tag color={activity.is_correct === null ? 'gold' : activity.is_correct ? 'green' : 'red'}>
                    {activity.is_correct === null ? '学习活动' : activity.is_correct ? '正确证据' : '错误证据'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="来源 Run">{activity.run_id || '-'}</Descriptions.Item>
              </Descriptions>
            ))}
          </Space>
        ) : <Empty description="该会话尚未产生学习事件" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Card>

      <Card
        className="agent-run-weaknesses"
        size="small"
        title={`本会话薄弱点（${session.weaknesses.summary.cluster_count}）`}
      >
        {session.weaknesses.clusters.length ? (
          <Space wrap>
            {session.weaknesses.clusters.map((cluster) => (
              <Tag color={cluster.status === 'due' ? 'red' : 'gold'} key={cluster.keyword}>
                {cluster.keyword} · 错误 {cluster.wrong_count}/{cluster.attempt_count}
              </Tag>
            ))}
          </Space>
        ) : <Empty description="当前会话没有错误评价证据" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Card>

      {session.turns.length === 0 ? (
        <Empty description="该会话暂无问答运行" />
      ) : (
        <Collapse
          className="turn-flow-collapse"
          defaultActiveKey={[String(session.turns.length)]}
          items={session.turns.map((turn) => ({
            key: String(turn.turn_number),
            label: (
              <div className="turn-flow-collapse__label">
                <span>第 {turn.turn_number} 轮</span>
                <Tag color={statusColors[turn.status] || 'default'}>
                  {statusLabels[turn.status] || turn.status}
                </Tag>
                <strong>
                  {(turn.user_message?.content || turn.input_message || '无输入').slice(0, 90)}
                </strong>
                <time>{dayjs(turn.created_at).format('MM-DD HH:mm:ss')}</time>
              </div>
            ),
            children: <TurnFlow turn={turn} />,
          }))}
        />
      )}

      <RunMemoryDrawer
        onClose={() => setMemoryOpen(false)}
        open={memoryOpen}
        threadId={session.thread_id}
      />
    </div>
  )
}

export default AgentRunDetailPage
