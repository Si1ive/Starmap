import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Table, Button, Input, Tag, Space, Card, Rate } from 'antd'
import { SearchOutlined, EyeOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getConversations } from '@/api'
const ConversationList = () => {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useState({
    page: 1,
    page_size: 20,
    q: '',
  })

  const { data, isLoading } = useQuery({
    queryKey: ['conversations', searchParams],
    queryFn: () => getConversations(searchParams),
  })

  const columns = [
    {
      title: '会话ID',
      dataIndex: 'id',
      width: 180,
      ellipsis: true,
    },
    {
      title: '用户问题',
      dataIndex: 'first_message',
      ellipsis: true,
    },
    {
      title: '对话轮数',
      dataIndex: 'message_count',
      width: 100,
    },
    {
      title: '对话时长',
      dataIndex: 'duration',
      width: 120,
      render: (duration: number) => `${Math.round(duration / 60)}分钟`,
    },
    {
      title: '涉及艺人',
      dataIndex: 'persons',
      render: (persons: string[]) => (
        <Space size={[0, 4]} wrap>
          {persons?.map((person) => (
            <Tag key={person}>{person}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '满意度',
      dataIndex: 'satisfaction',
      width: 120,
      render: (satisfaction: string) => {
        const rateMap: Record<string, number> = {
          good: 5,
          needs_improvement: 3,
          bad: 1,
        }
        return <Rate disabled defaultValue={rateMap[satisfaction] || 0} />
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, record: any) => (
        <Button type="text" icon={<EyeOutlined />} onClick={() => navigate(`/admin/conversations/${record.id}`)}>
          查看
        </Button>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>对话管理</h2>
      </div>

      <Card style={{ marginBottom: 24 }}>
        <Input.Search
          placeholder="搜索会话内容"
          allowClear
          enterButton={<><SearchOutlined /> 搜索</>}
          onSearch={(value) => setSearchParams((prev) => ({ ...prev, q: value, page: 1 }))}
          style={{ width: 400 }}
        />
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

export default ConversationList
