import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table,
  Button,
  Input,
  Select,
  Tag,
  Avatar,
  Space,
  Card,
  Popconfirm,
  message,
} from 'antd'
import { PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined, EyeOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getPersonList, deletePerson } from '@/api'
import type { Person } from '@/types'

const { Option } = Select

const statusMap: Record<string, { color: string; text: string }> = {
  complete: { color: 'success', text: '完整' },
  partial: { color: 'warning', text: '部分' },
  pending: { color: 'processing', text: '待审核' },
  processing: { color: 'default', text: '处理中' },
}

const PersonList = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useState({
    page: 1,
    page_size: 20,
    q: '',
    category: undefined as string | undefined,
    status: undefined as string | undefined,
  })

  const { data, isLoading } = useQuery({
    queryKey: ['persons', searchParams],
    queryFn: () => getPersonList(searchParams),
  })

  const deleteMutation = useMutation({
    mutationFn: deletePerson,
    onSuccess: () => {
      message.success('删除成功')
      queryClient.invalidateQueries({ queryKey: ['persons'] })
    },
    onError: () => {
      message.error('删除失败')
    },
  })

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 120,
      ellipsis: true,
    },
    {
      title: '头像',
      dataIndex: 'avatar',
      width: 80,
      render: (url: string) => <Avatar src={url} size={40} />,
    },
    {
      title: '姓名',
      dataIndex: 'name',
      sorter: true,
    },
    {
      title: '英文名',
      dataIndex: 'name_en',
      sorter: true,
    },
    {
      title: '分类',
      dataIndex: 'categories',
      render: (tags: string[]) => (
        <Space size={[0, 4]} wrap>
          {tags?.map((tag) => (
            <Tag key={tag}>{tag}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '国籍',
      dataIndex: 'nationality',
      sorter: true,
    },
    {
      title: '数据状态',
      dataIndex: 'status',
      render: (status: string) => {
        const config = statusMap[status] || { color: 'default', text: status }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      sorter: true,
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: Person) => (
        <Space>
          <Button
            type="text"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/admin/persons/${record.id}`)}
          >
            查看
          </Button>
          <Button
            type="text"
            icon={<EditOutlined />}
            onClick={() => navigate(`/admin/persons/${record.id}/edit`)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除"
            description="删除后不可恢复，是否继续？"
            onConfirm={() => deleteMutation.mutate(record.id)}
            okText="确认"
            cancelText="取消"
          >
            <Button type="text" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const handleSearch = (value: string) => {
    setSearchParams((prev) => ({ ...prev, q: value, page: 1 }))
  }

  const handleTableChange = (pagination: any, _filters: any, sorter: any) => {
    setSearchParams((prev) => ({
      ...prev,
      page: pagination.current,
      page_size: pagination.pageSize,
      sort_by: sorter.field,
      sort_order: sorter.order === 'ascend' ? 'asc' : 'desc',
    }))
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>艺人管理</h2>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/admin/persons/new')}
        >
          新增艺人
        </Button>
      </div>

      <Card style={{ marginBottom: 24 }}>
        <Space wrap>
          <Input.Search
            placeholder="搜索姓名、英文名、ID"
            allowClear
            enterButton={<><SearchOutlined /> 搜索</>}
            onSearch={handleSearch}
            style={{ width: 300 }}
          />
          <Select
            placeholder="分类筛选"
            allowClear
            style={{ width: 150 }}
            onChange={(value) => setSearchParams((prev) => ({ ...prev, category: value, page: 1 }))}
          >
            <Option value="actor">演员</Option>
            <Option value="singer">歌手</Option>
            <Option value="director">导演</Option>
          </Select>
          <Select
            placeholder="状态筛选"
            allowClear
            style={{ width: 150 }}
            onChange={(value) => setSearchParams((prev) => ({ ...prev, status: value, page: 1 }))}
          >
            <Option value="complete">完整</Option>
            <Option value="partial">部分</Option>
            <Option value="pending">待审核</Option>
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
        onChange={handleTableChange}
        scroll={{ x: 1200 }}
      />
    </div>
  )
}

export default PersonList
