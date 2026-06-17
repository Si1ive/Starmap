import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Tag, Avatar, Space, Timeline, Empty, Spin, Descriptions } from 'antd'
import { ArrowLeftOutlined, UserOutlined, RobotOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getConversationDetail } from '@/api'

interface ConversationMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  citations?: any[]
  llm_call_id?: string
  timestamp?: string
}

interface ConversationDetailData {
  id: string
  title?: string
  first_message?: string
  last_message?: string
  message_count: number
  has_knowledge?: boolean
  metadata_json?: Record<string, unknown>
  messages: ConversationMessage[]
  created_at?: string
  updated_at?: string
}

const ConversationDetail = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['conversation', id],
    queryFn: () => getConversationDetail(id!) as Promise<unknown> as Promise<{ data: ConversationDetailData }>,
    enabled: !!id,
  })

  const conversation = data?.data

  if (isLoading) {
    return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  }

  if (!conversation) {
    return <Empty description="对话不存在" />
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/conversations')}>返回</Button>
          <h2 style={{ margin: 0 }}>{conversation.title || '对话详情'}</h2>
        </Space>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Descriptions column={3} size="small">
          <Descriptions.Item label="会话 ID"><code>{conversation.id}</code></Descriptions.Item>
          <Descriptions.Item label="消息数">{conversation.message_count}</Descriptions.Item>
          <Descriptions.Item label="是否走过 RAG">{conversation.has_knowledge ? '是' : '否'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {conversation.created_at ? new Date(conversation.created_at).toLocaleString('zh-CN') : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {conversation.updated_at ? new Date(conversation.updated_at).toLocaleString('zh-CN') : '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="对话内容">
        {!conversation.messages || conversation.messages.length === 0 ? (
          <Empty description="暂无消息" />
        ) : (
          <Timeline mode="left" style={{ marginTop: 16 }}>
            {conversation.messages.map((msg) => (
              <Timeline.Item
                key={msg.id}
                dot={
                  msg.role === 'user' ? (
                    <Avatar icon={<UserOutlined />} style={{ background: '#1890ff' }} />
                  ) : (
                    <Avatar icon={<RobotOutlined />} style={{ background: '#52c41a' }} />
                  )
                }
                label={msg.timestamp ? new Date(msg.timestamp).toLocaleString('zh-CN') : ''}
              >
                <div
                  style={{
                    background: msg.role === 'user' ? '#e6f7ff' : '#f6ffed',
                    padding: 12,
                    borderRadius: 8,
                    marginBottom: 8,
                  }}
                >
                  <div style={{ fontWeight: 500, marginBottom: 4 }}>
                    {msg.role === 'user' ? '用户' : msg.role === 'assistant' ? 'AI 助手' : '系统'}
                    {msg.llm_call_id && (
                      <Tag color="purple" style={{ marginLeft: 8, cursor: 'pointer' }}
                        icon={<ThunderboltOutlined />}
                        onClick={() => navigate(`/admin/monitor/llm`)}>
                        LLM 调用
                      </Tag>
                    )}
                  </div>
                  <div style={{ lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>{msg.content}</div>
                  {msg.citations && msg.citations.length > 0 && (
                    <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px dashed #d9d9d9' }}>
                      <span style={{ fontSize: 12, color: '#666' }}>引用来源:</span>
                      <Space size={[0, 4]} wrap style={{ marginLeft: 8 }}>
                        {msg.citations.map((c: any, idx: number) => (
                          <Tag key={idx} color="blue">{c.name || c.title || JSON.stringify(c)}</Tag>
                        ))}
                      </Space>
                    </div>
                  )}
                </div>
              </Timeline.Item>
            ))}
          </Timeline>
        )}
      </Card>
    </div>
  )
}

export default ConversationDetail
