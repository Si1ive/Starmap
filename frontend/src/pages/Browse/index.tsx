import React, { useState, useEffect, useCallback } from 'react'
import { Card, Row, Col, Tag, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { searchPersons } from '@/api/person'
import PersonCard from '@/components/PersonCard'
import Loading from '@/components/Loading'
import type { IPerson } from '@/types'

const { Title, Text } = Typography

interface Category {
  name: string
  key: string
  count: number
  description: string
}

const categories: Category[] = [
  { name: '演员', key: 'actor', count: 0, description: '电影、电视剧演员' },
  { name: '歌手', key: 'singer', count: 0, description: '流行、摇滚、民谣歌手' },
  { name: '导演', key: 'director', count: 0, description: '电影、电视剧导演' },
  { name: '编剧', key: 'writer', count: 0, description: '影视编剧' },
]

const BrowsePage: React.FC = () => {
  const navigate = useNavigate()
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [persons, setPersons] = useState<IPerson[]>([])
  const [loading, setLoading] = useState(false)
  const [categoryCounts, setCategoryCounts] = useState<Record<string, number>>({})

  // 获取分类数量
  const fetchCategoryCounts = useCallback(async () => {
    const counts: Record<string, number> = {}
    for (const cat of categories) {
      try {
        const response = await searchPersons({
          q: '',
          category: cat.key,
          page_size: 1
        })
        const data = (response as any)?.data || response
        counts[cat.key] = data?.total || 0
      } catch {
        counts[cat.key] = 0
      }
    }
    setCategoryCounts(counts)
  }, [])

  useEffect(() => {
    fetchCategoryCounts()
  }, [fetchCategoryCounts])

  // 获取分类下的人物
  const fetchPersonsByCategory = useCallback(async (category: string) => {
    setLoading(true)
    try {
      const response = await searchPersons({
        q: '',
        category,
        page: 1,
        page_size: 20
      })
      const data = (response as any)?.data || response
      setPersons(data?.items || [])
    } catch (error) {
      console.error('获取分类数据错误:', error)
      message.error('获取数据失败，请稍后重试')
      setPersons([])
    } finally {
      setLoading(false)
    }
  }, [])

  const handleCategoryClick = useCallback((categoryKey: string) => {
    if (selectedCategory === categoryKey) {
      setSelectedCategory(null)
      setPersons([])
    } else {
      setSelectedCategory(categoryKey)
      fetchPersonsByCategory(categoryKey)
    }
  }, [selectedCategory, fetchPersonsByCategory])

  const handlePersonClick = useCallback((id: string) => {
    navigate(`/person/${id}`)
  }, [navigate])

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>
      <Title level={3} style={{ marginBottom: 24 }}>
        领域浏览
      </Title>

      {/* 分类卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 32 }}>
        {categories.map((cat) => (
          <Col xs={24} sm={12} md={8} lg={6} key={cat.key}>
            <Card
              hoverable
              onClick={() => handleCategoryClick(cat.key)}
              style={{
                borderColor: selectedCategory === cat.key ? '#1890ff' : undefined,
                backgroundColor: selectedCategory === cat.key ? '#e6f7ff' : undefined
              }}
            >
              <div style={{ textAlign: 'center' }}>
                <Title level={4} style={{ margin: '0 0 8px' }}>
                  {cat.name}
                </Title>
                <Tag color="blue">
                  {categoryCounts[cat.key] !== undefined
                    ? `${categoryCounts[cat.key]} 人`
                    : '加载中...'}
                </Tag>
                <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
                  {cat.description}
                </Text>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 选中分类的人物列表 */}
      {selectedCategory && (
        <div>
          <Title level={4} style={{ marginBottom: 16 }}>
            {categories.find((c) => c.key === selectedCategory)?.name}列表
          </Title>
          <Loading loading={loading} empty={persons.length === 0} emptyDescription="该分类暂无数据">
            <Row gutter={[16, 16]}>
              {persons.map((person) => (
                <Col xs={24} sm={12} md={8} key={person.id}>
                  <PersonCard person={person} onClick={handlePersonClick} />
                </Col>
              ))}
            </Row>
          </Loading>
        </div>
      )}
    </div>
  )
}

export default BrowsePage
