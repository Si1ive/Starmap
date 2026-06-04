import { useState } from 'react'
import { Table, Button, Input, Select, Tag, Space, Card } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import type { Work } from '@/types'

// 模拟API调用
const mockGetWorkList = async (params: any) => {
  return {
    code: 200,
    data: {
      items: [] as Work[],
      total: 0,
      page: params.page || 1,
      page_size: params.page_size || 20,
      total_pages: 0,
    },
    message: 'success',
    request_id: 'mock',
  }
}

const { Option } = Select

const workTypeMap: Record<string, { color: string; text: string }> = {
  movie: { color: 'blue', text: '电影' },
  tv: { color: 'purple', text: '电视剧' },
  album: { color: 'green', text: '专辑' },
  single: { color: 'orange', text: '单曲' },
  book: { color: 'cyan', text: '书籍' },
}

const WorkList = () => {
  const [searchParams, setSearchParams] = useState({
    page: 1,
    page_size: 20,
    q: '',
    type: undefined as string | undefined,
  })

  const { data, isLoading } = useQuery({
    queryKey: ['works', searchParams],
    queryFn: () => mockGetWorkList(searchParams),
  })

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 120,
    },
    {
      title: '标题',
      dataIndex: 'title',
    },
    {
      title: '类型',
      dataIndex: 'type',
      render: (type: string) => {
        const config = workTypeMap[type] || { color: 'default', text: type }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '年份',
      dataIndex: 'year',
      sorter: true,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
    },
    {
      title: '操作',
      key: 'action',
      render: () => (
        <Space>
          <Button type="text">查看</Button>
          <Button type="text">编辑</Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>作品管理</h2>
        <Button type="primary" icon={<PlusOutlined />}>
          新增作品
        </Button>
      </div>

      <Card style={{ marginBottom: 24 }}>
        <Space wrap>
          <Input.Search
            placeholder="搜索作品标题"
            allowClear
            enterButton={<><SearchOutlined /> 搜索</>}
            onSearch={(value) => setSearchParams((prev) => ({ ...prev, q: value, page: 1 }))}
            style={{ width: 300 }}
          />
          <Select
            placeholder="类型筛选"
            allowClear
            style={{ width: 150 }}
            onChange={(value) => setSearchParams((prev) => ({ ...prev, type: value, page: 1 }))}
          >
            <Option value="movie">电影</Option>
            <Option value="tv">电视剧</Option>
            <Option value="album">专辑</Option>
            <Option value="single">单曲</Option>
            <Option value="book">书籍</Option>
          </Select>
        </Space>
      </Card>

      <Table
        columns={columns}
        dataSource={data?.data?.items || []}
        rowKey="id"
        loading={isLoading}
        pagination={{
          current: searchParams.page,
          pageSize: searchParams.page_size,
          total: data?.data?.total || 0,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
        }}
        onChange={(pagination) =>
          setSearchParams((prev) => ({
            ...prev,
            page: pagination.current || 1,
            page_size: pagination.pageSize || 20,
          }))
        }
      />
    </div>
  )
}

export default WorkList
