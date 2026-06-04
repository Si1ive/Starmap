import React, { useState, useCallback } from 'react'
import { Input, List, Typography, message } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { searchPersons } from '@/api/person'
import { useAppStore } from '@/store'
import PersonCard from '@/components/PersonCard'
import Loading from '@/components/Loading'
import type { IPerson } from '@/types'

const { Search } = Input
const { Title } = Typography

const SearchPage: React.FC = () => {
  const [results, setResults] = useState<IPerson[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const navigate = useNavigate()
  const addSearchHistory = useAppStore((state) => state.addSearchHistory)

  const handleSearch = useCallback(async (value: string) => {
    if (!value.trim()) return

    setLoading(true)
    setSearched(true)

    try {
      const response = await searchPersons({
        q: value.trim(),
        page: 1,
        page_size: 20
      })

      // 适配 API 响应格式 { code, data, message, request_id }
      const data = (response as any)?.data || response
      const items = data?.items || []
      setResults(items)
      addSearchHistory(value.trim())
    } catch (error) {
      console.error('搜索错误:', error)
      message.error('搜索失败，请稍后重试')
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [addSearchHistory])

  const handlePersonClick = useCallback((id: string) => {
    navigate(`/person/${id}`)
  }, [navigate])

  return (
    <div style={{ maxWidth: 900, margin: '0 auto' }}>
      <Title level={2} style={{ textAlign: 'center', marginBottom: 40 }}>
        StarMap 艺人知识图谱
      </Title>

      <Search
        placeholder="搜索艺人、作品..."
        enterButton={<><SearchOutlined /> 搜索</>}
        size="large"
        onSearch={handleSearch}
        loading={loading}
        style={{ marginBottom: 40 }}
      />

      <Loading
        loading={loading}
        empty={searched && results.length === 0}
        emptyDescription="未找到相关艺人"
      >
        <List
          grid={{
            gutter: 16,
            xs: 1,
            sm: 2,
            md: 2,
            lg: 3,
            xl: 3
          }}
          dataSource={results}
          renderItem={(person) => (
            <List.Item>
              <PersonCard
                person={person}
                onClick={handlePersonClick}
              />
            </List.Item>
          )}
        />
      </Loading>
    </div>
  )
}

export default SearchPage
