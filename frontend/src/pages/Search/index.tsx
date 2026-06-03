import React, { useState } from 'react'
import { Input, Card, List, Typography, Tag } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { Search } = Input
const { Title, Text } = Typography

interface Person {
  id: string
  name: string
  avatar?: string
  categories: string[]
  summary: string
}

const SearchPage: React.FC = () => {
  const [results, setResults] = useState<Person[]>([])
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSearch = async (value: string) => {
    if (!value.trim()) return
    
    setLoading(true)
    // TODO: 调用API
    setResults([])
    setLoading(false)
  }

  const handlePersonClick = (id: string) => {
    navigate(`/person/${id}`)
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Title level={2} style={{ textAlign: 'center', marginBottom: 40 }}>
        StarMap 艺人知识图谱
      </Title>
      
      <Search
        placeholder="搜索艺人、作品..."
        enterButton={<SearchOutlined />}
        size="large"
        onSearch={handleSearch}
        loading={loading}
        style={{ marginBottom: 40 }}
      />

      <List
        grid={{ gutter: 16, xs: 1, sm: 2, md: 2, lg: 2, xl: 2 }}
        dataSource={results}
        renderItem={(person) => (
          <List.Item>
            <Card
              hoverable
              onClick={() => handlePersonClick(person.id)}
            >
              <Card.Meta
                title={person.name}
                description={
                  <>
                    <div style={{ marginBottom: 8 }}>
                      {person.categories.map(cat => (
                        <Tag key={cat}>{cat}</Tag>
                      ))}
                    </div>
                    <Text type="secondary" ellipsis>
                      {person.summary}
                    </Text>
                  </>
                }
              />
            </Card>
          </List.Item>
        )}
      />
    </div>
  )
}

export default SearchPage
