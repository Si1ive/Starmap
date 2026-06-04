import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Input, Button, List, Avatar, Typography, message } from 'antd'
import { UserOutlined, RobotOutlined } from '@ant-design/icons'
import { sendMessage, getChatHistory } from '@/api/chat'
import { useAppStore } from '@/store'
import type { IMessage } from '@/types'

const { TextArea } = Input
const { Text } = Typography

const ChatPage: React.FC = () => {
  const [messages, setMessages] = useState<IMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const sessionId = useAppStore((state) => state.sessionId)
  const setSessionId = useAppStore((state) => state.setSessionId)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  // 如果有sessionId，加载历史对话
  useEffect(() => {
    const loadHistory = async () => {
      if (!sessionId) return
      try {
        const history = await getChatHistory(sessionId)
        if (history.messages) {
          setMessages(history.messages.map((msg, index) => ({
            id: `${sessionId}-${index}`,
            role: msg.role as 'user' | 'assistant' | 'system',
            content: msg.content,
            timestamp: msg.timestamp || new Date().toISOString()
          })))
        }
      } catch (error) {
        console.error('加载对话历史失败:', error)
      }
    }
    loadHistory()
  }, [sessionId])

  const handleSend = useCallback(async () => {
    if (!input.trim()) return

    const userMessage: IMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date().toISOString()
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setLoading(true)

    try {
      const data = await sendMessage({
        message: userMessage.content,
        session_id: sessionId || undefined
      })

      // 保存 session_id
      if (data.session_id && !sessionId) {
        setSessionId(data.session_id)
      }

      const assistantMessage: IMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.message || '抱歉，我没有理解您的问题。',
        timestamp: new Date().toISOString()
      }

      setMessages((prev) => [...prev, assistantMessage])
    } catch (error) {
      console.error('对话错误:', error)
      message.error('发送消息失败，请稍后重试')

      const errorMessage: IMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: '抱歉，服务暂时不可用，请稍后重试。',
        timestamp: new Date().toISOString()
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setLoading(false)
    }
  }, [input, sessionId, setSessionId])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend]
  )

  return (
    <div
      style={{
        maxWidth: 800,
        margin: '0 auto',
        height: 'calc(100vh - 200px)',
        display: 'flex',
        flexDirection: 'column'
      }}
    >
      {/* 消息列表 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '20px 0' }}>
        {messages.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: '60px 20px',
              color: '#999'
            }}
          >
            <RobotOutlined style={{ fontSize: 48, marginBottom: 16 }} />
            <div style={{ fontSize: 16 }}>StarMap 智能助手</div>
            <Text type="secondary">
              您可以问我关于艺人的任何问题，例如：
              <br />
              "周杰伦的妻子是谁？"
              <br />
              "推荐几个和周杰伦风格相似的歌手"
            </Text>
          </div>
        ) : (
          <List
            dataSource={messages}
            renderItem={(msg) => (
              <List.Item
                style={{
                  justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  padding: '8px 0'
                }}
              >
                <div
                  style={{
                    maxWidth: '75%',
                    padding: '12px 16px',
                    borderRadius: msg.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                    background: msg.role === 'user' ? '#1890ff' : '#f5f5f5',
                    color: msg.role === 'user' ? '#fff' : '#333',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.1)'
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      marginBottom: 8,
                      gap: 8
                    }}
                  >
                    <Avatar
                      icon={msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                      size="small"
                      style={{
                        backgroundColor: msg.role === 'user' ? '#096dd9' : '#52c41a',
                        color: '#fff'
                      }}
                    />
                    <Text
                      style={{
                        fontSize: 12,
                        color: msg.role === 'user' ? 'rgba(255,255,255,0.85)' : '#666'
                      }}
                    >
                      {msg.role === 'user' ? '你' : 'StarMap Agent'}
                    </Text>
                  </div>
                  <div style={{ lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div style={{ padding: '16px 0', borderTop: '1px solid #e8e8e8' }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
          <TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入消息..."
            autoSize={{ minRows: 1, maxRows: 4 }}
            onKeyDown={handleKeyDown}
            disabled={loading}
            style={{ flex: 1, borderRadius: 8 }}
          />
          <Button
            type="primary"
            onClick={handleSend}
            loading={loading}
            disabled={!input.trim()}
            style={{ height: 40 }}
          >
            发送
          </Button>
        </div>
        <Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
          按 Enter 发送，Shift + Enter 换行
        </Text>
      </div>
    </div>
  )
}

export default ChatPage
