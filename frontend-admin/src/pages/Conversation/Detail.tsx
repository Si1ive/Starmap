import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Tag, Avatar, Badge, Rate, Space, Timeline } from 'antd'
import { ArrowLeftOutlined, UserOutlined, RobotOutlined, CheckCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getConversationDetail } from '@/api'

const satisfactionMap: Record<string, { text: string; color: string }> = {
  good: { text: '满意', color: 'green' },
  needs_improvement: { text: '需改进', color: 'orange' },
  bad: { text: '不满意', color: 'red' },
}

interface ConversationDetailData {
  id: string
  first_message: string
  message_count: number
  duration: number
  messages: any[]
  persons: string[]
  satisfaction?: string
  created_at: string
  updated_at: string
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
    return <div>加载中...</div>
  }

  if (!conversation) {
    return <div>对话不存在</div>
  }

  const satisfaction = (conversation.satisfaction && satisfactionMap[conversation.satisfaction]) || { text: '未标注', color: 'default' }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/conversations')}>
            返回
          </Button>
          <h2 style={{ margin: 0 }}>对话详情</h2>
        </div>
        <Space>
          <Badge color={satisfaction.color} text={satisfaction.text} />
          {conversation.satisfaction && (
            <Rate disabled defaultValue={satisfactionMap[conversation.satisfaction] ? 5 : 3} />
          )}
        </Space>
      </div>

      <Card style={{ marginBottom: 24 }}>
        <div style={{ marginBottom: 16 }}>
          <h3 style={{ margin: '0 0 8px 0' }}>会话信息</h3>
          <Space size={16}>
            <span>ID: <code>{conversation.id}</code></span>
            <span>对话轮数: {conversation.message_count}</span>
            <span>时长: {Math.round(conversation.duration / 60)}分钟</span>
          </Space>
        </div>
        <div>
          <span style={{ marginRight: 8 }}>涉及艺人:</span>
          {conversation.persons?.map((person: string) => (
            <Tag key={person}>{person}</Tag>
          ))}
        </div>
      </Card>

      <Card title="对话内容">
        <Timeline mode="left">
          {conversation.messages?.map((msg: any) => (
            <Timeline.Item
              key={msg.id}
              dot={
                msg.role === 'user' ? (
                  <Avatar icon={<UserOutlined />} style={{ background: '#1890ff' }} />
                ) : (
                  <Avatar icon={<RobotOutlined />} style={{ background: '#52c41a' }} />
                )
              }
              label={msg.timestamp}
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
                  {msg.role === 'user' ? '用户' : 'AI助手'}
                </div>
                <div style={{ lineHeight: 1.8 }}>{msg.content}</div>
                {msg.sources && msg.sources.length > 0 && (
                  <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px dashed #d9d9d9' }}>
                    <span style={{ fontSize: 12, color: '#666' }}>知识来源:</span>
                    <Space size={[0, 4]} wrap style={{ marginLeft: 8 }}>
                      {msg.sources.map((source: any, index: number) => (
                        <Tag key={index} color="blue">
                          {source.name}
                          {source.relation && ` (${source.relation})`}
                        </Tag>
                      ))}
                    </Space>
                  </div>
                )}
              </div>
            </Timeline.Item>
          ))}
        </Timeline>
      </Card>

      <Card title="质量标注" style={{ marginTop: 24 }}>
        <Space>
          <Button type="primary" icon={<CheckCircleOutlined />}>
            标记为优质
          </Button>
          <Button icon={<ExclamationCircleOutlined />}>
            标记为需改进
          </Button>
          <Button danger>标记为错误</Button>
        </Space>
      </Card>
    </div>
  )
}

export default ConversationDetail
