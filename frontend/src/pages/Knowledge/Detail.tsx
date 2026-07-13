import React from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Tag, Button, Typography, Space, Divider, Spin, Empty } from 'antd'
import { ArrowLeftOutlined, BookOutlined, FireOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getKnowledgePointDetail } from '@/api/knowledge'

const { Title, Text } = Typography

const difficultyConfig: Record<string, { color: string; text: string }> = {
  easy: { color: 'green', text: '简单' },
  medium: { color: 'orange', text: '中等' },
  hard: { color: 'red', text: '困难' },
}

const examFreqConfig: Record<string, { color: string; text: string; icon?: React.ReactNode }> = {
  high: { color: 'red', text: '高频', icon: <FireOutlined /> },
  medium: { color: 'orange', text: '中频' },
  low: { color: 'blue', text: '低频' },
  never: { color: 'default', text: '未考' },
}

const KnowledgeDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['knowledgePoint', id],
    queryFn: () => getKnowledgePointDetail(id || ''),
    enabled: !!id,
  })

  const point = data?.data

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  if (!point) {
    return (
      <div style={{ maxWidth: 800, margin: '0 auto', padding: 24 }}>
        <Empty description="知识点不存在" />
      </div>
    )
  }

  const diff = difficultyConfig[point.difficulty] || { color: 'default', text: point.difficulty }
  const freq = examFreqConfig[point.exam_frequency] || { color: 'default', text: point.exam_frequency }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 24 }}>
      <Button
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(-1)}
        style={{ marginBottom: 16 }}
      >
        返回
      </Button>

      <Card>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          {/* 标题和标签 */}
          <div>
            <Title level={3} style={{ marginBottom: 8 }}>
              <BookOutlined /> {point.title}
            </Title>
            <Space>
              <Tag color={diff.color}>{diff.text}</Tag>
              <Tag color={freq.color}>{freq.icon} {freq.text}</Tag>
              {point.tags?.map((tag) => (
                <Tag key={tag}>{tag}</Tag>
              ))}
            </Space>
          </div>

          <Divider />

          {/* 知识点内容 */}
          <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8, fontSize: 15 }}>
            {point.content}
          </div>

          {/* 要点 */}
          {point.key_points && point.key_points.length > 0 && (
            <>
              <Divider />
              <div>
                <Title level={5}>要点</Title>
                <ol style={{ paddingLeft: 20 }}>
                  {point.key_points.map((kp, idx) => (
                    <li key={idx} style={{ marginBottom: 8, lineHeight: 1.6 }}>
                      {kp}
                    </li>
                  ))}
                </ol>
              </div>
            </>
          )}

          {/* 来源 */}
          {point.source && (
            <>
              <Divider />
              <Text type="secondary">来源：{point.source} {point.source_page || ''}</Text>
            </>
          )}
        </Space>
      </Card>
    </div>
  )
}

export default KnowledgeDetailPage
