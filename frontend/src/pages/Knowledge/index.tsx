import React, { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Card, List, Tag, Input, Select, Space, Typography, Empty, Spin } from 'antd'
import { BookOutlined, FireOutlined, StarOutlined } from '@ant-design/icons'
import { searchKnowledgePoints, getSubjects, getChapters } from '@/api/knowledge'
import type { IKnowledgePointListItem, ISubject, IChapter } from '@/types'

const { Title, Paragraph, Text } = Typography
const { Search } = Input

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

const KnowledgePage: React.FC = () => {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [loading, setLoading] = useState(false)
  const [points, setPoints] = useState<IKnowledgePointListItem[]>([])
  const [total, setTotal] = useState(0)
  const [subjects, setSubjects] = useState<ISubject[]>([])
  const [chapters, setChapters] = useState<IChapter[]>([])
  const [page, setPage] = useState(1)

  const keyword = searchParams.get('q') || ''
  const subjectId = searchParams.get('subject_id') || ''
  const chapterId = searchParams.get('chapter_id') || ''
  const difficulty = searchParams.get('difficulty') || ''

  // Load subjects
  useEffect(() => {
    getSubjects().then((res) => {
      if (res.data) setSubjects(Array.isArray(res.data) ? res.data : [])
    })
  }, [])

  // Load chapters when subject changes
  useEffect(() => {
    if (subjectId) {
      getChapters(subjectId).then((res) => {
        if (res.data) setChapters(Array.isArray(res.data) ? res.data : [])
      })
    } else {
      setChapters([])
    }
  }, [subjectId])

  // Search knowledge points
  useEffect(() => {
    setLoading(true)
    searchKnowledgePoints({
      q: keyword || undefined,
      subject_id: subjectId || undefined,
      chapter_id: chapterId || undefined,
      difficulty: difficulty || undefined,
      page,
      page_size: 20,
    }).then((res) => {
      if (res.data) {
        setPoints(res.data.items || [])
        setTotal(res.data.total || 0)
      }
    }).finally(() => setLoading(false))
  }, [keyword, subjectId, chapterId, difficulty, page])

  const handleSearch = (value: string) => {
    const params = new URLSearchParams(searchParams)
    if (value) {
      params.set('q', value)
    } else {
      params.delete('q')
    }
    params.delete('page')
    setSearchParams(params)
  }

  const handleFilterChange = (key: string, value: string) => {
    const params = new URLSearchParams(searchParams)
    if (value && value !== 'all') {
      params.set(key, value)
    } else {
      params.delete(key)
    }
    params.delete('page')
    setSearchParams(params)
  }

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px' }}>
      <Title level={3}>
        <BookOutlined /> 知识库
      </Title>

      {/* 搜索和筛选 */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap style={{ width: '100%' }}>
          <Search
            placeholder="搜索知识点"
            style={{ width: 300 }}
            defaultValue={keyword}
            onSearch={handleSearch}
            allowClear
          />
          <Select
            value={subjectId || 'all'}
            style={{ width: 150 }}
            onChange={(value) => handleFilterChange('subject_id', value)}
            options={[
              { label: '全部学科', value: 'all' },
              ...subjects.map((s) => ({ label: s.name, value: s.id })),
            ]}
          />
          {subjectId && chapters.length > 0 && (
            <Select
              value={chapterId || 'all'}
              style={{ width: 150 }}
              onChange={(value) => handleFilterChange('chapter_id', value)}
              options={[
                { label: '全部章节', value: 'all' },
                ...chapters.map((c) => ({ label: c.name, value: c.id })),
              ]}
            />
          )}
          <Select
            value={difficulty || 'all'}
            style={{ width: 120 }}
            onChange={(value) => handleFilterChange('difficulty', value)}
            options={[
              { label: '全部难度', value: 'all' },
              { label: '简单', value: 'easy' },
              { label: '中等', value: 'medium' },
              { label: '困难', value: 'hard' },
            ]}
          />
        </Space>
      </Card>

      {/* 知识点列表 */}
      <Card>
        <Spin spinning={loading}>
          {points.length === 0 && !loading ? (
            <Empty description="暂无知识点，请先通过管理后台导入PDF" />
          ) : (
            <List
              dataSource={points}
              pagination={{
                current: page,
                total,
                pageSize: 20,
                showTotal: (count) => `共 ${count} 条`,
                onChange: setPage,
              }}
              renderItem={(point) => {
                const diff = difficultyConfig[point.difficulty] || { color: 'default', text: point.difficulty }
                const freq = examFreqConfig[point.exam_frequency] || { color: 'default', text: point.exam_frequency }
                return (
                  <List.Item
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/knowledge/${point.id}`)}
                  >
                    <List.Item.Meta
                      title={
                        <Space>
                          <span>{point.title}</span>
                          <Tag color={diff.color}>{diff.text}</Tag>
                          <Tag color={freq.color}>{freq.icon} {freq.text}</Tag>
                        </Space>
                      }
                      description={
                        <div>
                          <Text type="secondary" style={{ fontSize: 13 }}>
                            {point.content.slice(0, 150)}...
                          </Text>
                          {point.tags && point.tags.length > 0 && (
                            <div style={{ marginTop: 4 }}>
                              {point.tags.map((tag) => (
                                <Tag key={tag} style={{ fontSize: 11 }}>{tag}</Tag>
                              ))}
                            </div>
                          )}
                        </div>
                      }
                    />
                  </List.Item>
                )
              }}
            />
          )}
        </Spin>
      </Card>
    </div>
  )
}

export default KnowledgePage
