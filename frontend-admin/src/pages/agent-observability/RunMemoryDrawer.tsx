import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Collapse,
  Drawer,
  Empty,
  Row,
  Col,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd'
import { HistoryOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import * as agentRunsApi from '@/api/agentRuns'
import type { AdminConversationMemory, AdminConversationMemoryTurn } from '@/api/agentRuns'
import PlainDataBlock from './PlainDataBlock'

const { Text, Title } = Typography

interface RunMemoryDrawerProps {
  open: boolean
  threadId: string | null
  onClose: () => void
}

const sectionLabels: Record<string, string> = {
  thread_state: '线程热状态',
  snapshot: '本轮上下文快照',
  memory_events: '可信记忆事实',
  memory_items: '长期记忆项',
  mastery: '学习掌握度',
  summaries: '会话摘要',
}

function TurnMemoryChange({ turn }: { turn: AdminConversationMemoryTurn }) {
  return (
    <Collapse
      className={`conversation-memory-turn ${turn.changed ? 'is-changed' : 'is-unchanged'}`}
      items={[
        {
          key: turn.root_run_id,
          label: (
            <div className="conversation-memory-turn__label">
              <span className="conversation-memory-turn__number">第 {turn.turn_number} 轮</span>
              <Tag color={turn.changed ? 'processing' : 'default'}>
                {turn.changed ? `${turn.changed_sections.length} 类记忆变化` : '未观测到记忆变化'}
              </Tag>
              <strong>{turn.input_message || '（无文本输入）'}</strong>
              <time>{dayjs(turn.observed_at).format('MM-DD HH:mm:ss')}</time>
            </div>
          ),
          children: turn.changed ? (
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <div className="conversation-memory-sections" aria-label="发生变化的记忆域">
                {turn.changed_sections.map((section) => (
                  <Tag color="blue" key={section}>
                    {sectionLabels[section] || section}
                  </Tag>
                ))}
              </div>
              <Row gutter={[12, 12]}>
                <Col xs={24} lg={12}>
                  <Text strong>本轮开始前</Text>
                  <PlainDataBlock value={turn.before} maxHeight={420} />
                </Col>
                <Col xs={24} lg={12}>
                  <Text strong>本轮结束后</Text>
                  <PlainDataBlock value={turn.after} maxHeight={420} />
                </Col>
              </Row>
            </Space>
          ) : (
            <Alert
              message={
                turn.trace_count
                  ? '本轮有观测记录，但记忆状态与上一轮一致'
                  : '本轮没有可用的记忆观测记录'
              }
              description="这里不把步骤入参、模型输出或派生任务状态算作上下文记忆变化。"
              showIcon
              type="info"
            />
          ),
        },
      ]}
      size="small"
    />
  )
}

const RunMemoryDrawer = ({ open, threadId, onClose }: RunMemoryDrawerProps) => {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<AdminConversationMemory | null>(null)

  useEffect(() => {
    if (!open || !threadId) return
    setLoading(true)
    setData(null)
    void agentRunsApi
      .getConversationMemory(threadId)
      .then((response) => setData(response.data || null))
      .catch(() => {
        setData(null)
        message.error('会话记忆变化加载失败')
      })
      .finally(() => setLoading(false))
  }, [open, threadId])

  const changedTurns = useMemo(
    () => data?.turns.filter((turn) => turn.changed) || [],
    [data?.turns]
  )

  return (
    <Drawer
      className="memory-observability-drawer conversation-memory-drawer"
      destroyOnClose
      onClose={onClose}
      open={open}
      title="会话上下文记忆变化"
      width="min(1040px, 96vw)"
    >
      {loading ? (
        <div className="admin-page-loading">
          <Spin size="large" />
        </div>
      ) : !data ? (
        <Empty description="无法读取该会话的记忆变化" />
      ) : (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <header className="conversation-memory-hero">
            <div>
              <Text type="secondary">{data.thread.id}</Text>
              <Title level={4}>{data.thread.title}</Title>
              <Text>按对话轮次连续比较上下文记忆，只呈现持久记忆域的前后变化。</Text>
            </div>
            <div className="conversation-memory-hero__count" aria-label="记忆变化轮次">
              <HistoryOutlined />
              <strong>{data.changed_turn_count}</strong>
              <span>轮发生变化 / 共 {data.turns.length} 轮</span>
            </div>
          </header>

          <Alert
            message="这里专门回答：会话记忆在每一轮之后变成了什么"
            description="运行步骤的入参、出参和工具证据仍在会话详情流程图中查看；这里不展示运行上下文轨迹，也不提供 Run、Snapshot 或派生任务回放。"
            showIcon
            type="info"
          />

          {data.turns.length ? (
            <div className="conversation-memory-timeline">
              {data.turns.map((turn) => (
                <TurnMemoryChange key={turn.root_run_id} turn={turn} />
              ))}
            </div>
          ) : (
            <Empty description="该会话还没有可比较的对话轮次" />
          )}

          {data.turns.length > 0 && changedTurns.length === 0 ? (
            <Alert
              message="现有历史记录中没有可比较出的变化"
              description="可能是会话早于记忆观测功能创建；后续新轮次会继续在同一时间线上比较。"
              showIcon
              type="warning"
            />
          ) : null}
        </Space>
      )}
    </Drawer>
  )
}

export default RunMemoryDrawer
