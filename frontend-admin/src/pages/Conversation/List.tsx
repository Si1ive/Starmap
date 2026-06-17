import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Table, Button, Input, Tag, Card, Popconfirm, message } from 'antd'
import { SearchOutlined, EyeOutlined, DeleteOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getConversations, deleteConversation } from '@/api'

const ConversationList = () => {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useState({
    page: 1,
    page_size: 20,
    q: '',
  })

  const { data, isLoading } = useQuery({
    queryKey: ['conversations', searchParams],
    queryFn: () => getConversations(searchParams),
  })

  const delMut = useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onSuccess: () => {
      message.success('删除成功')
      qc.invalidateQueries({ queryKey: ['conversations'] })
    },
    onError: () => message.error('删除失败'),
  })

  const columns = [
    { title: '会话ID', dataIndex: 'id', width: 220, ellipsis: true,
      render: (v: string) => <code style={{ fontSize: 12 }}>{v}</code> },
    { title: '标题/首条消息', dataIndex: 'title', ellipsis: true,
      render: (_: unknown, r: any) => r.title || r.first_message || '-' },
    { title: '消息数', dataIndex: 'message_count', width: 90 },
    { title: '是否走 RAG', dataIndex: 'has_knowledge', width: 100,
      render: (v: boolean) => v ? <Tag color="green">是</Tag> : <Tag>否</Tag> },
    {
      title: '最后消息',
      dataIndex: 'last_message',
      ellipsis: true,
      render: (v: string) => <span style={{ color: '#666', fontSize: 12 }}>{v || '-'}</span>,
    },
    { title: '更新时间', dataIndex: 'updated_at', width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
    {
      title: '操作', key: 'action', width: 160,
      render: (_: unknown, record: any) => (
        <>
          <Button type="link" icon={<EyeOutlined />} size="small"
            onClick={() => navigate(`/admin/conversations/${record.id}`)}>查看</Button>
          <Popconfirm title={`删除会话 ${record.id}？`} onConfirm={() => delMut.mutate(record.id)}>
            <Button type="link" icon={<DeleteOutlined />} danger size="small">删除</Button>
          </Popconfirm>
        </>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>对话管理</h2>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="搜索标题或首条消息"
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
        size="small"
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
