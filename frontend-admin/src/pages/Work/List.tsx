import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table,
  Button,
  Input,
  Select,
  Tag,
  Space,
  Card,
  Popconfirm,
  message,
  Image,
  Rate,
} from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  EyeOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getWorkList, deleteWork } from '@/api'
import type { Work } from '@/types'

const { Option } = Select

const workTypeMap: Record<string, { color: string; text: string }> = {
  movie: { color: 'blue', text: '电影' },
  tv: { color: 'purple', text: '电视剧' },
  album: { color: 'green', text: '专辑' },
  single: { color: 'orange', text: '单曲' },
  book: { color: 'cyan', text: '书籍' },
}

const statusMap: Record<string, { color: string; text: string }> = {
  complete: { color: 'success', text: '完整' },
  partial: { color: 'warning', text: '部分' },
  pending: { color: 'processing', text: '待审核' },
}

const WorkList = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useState({
    page: 1,
    page_size: 20,
    q: '',
    type: undefined as string | undefined,
    year: undefined as number | undefined,
  })

  const { data, isLoading } = useQuery({
    queryKey: ['works', searchParams],
    queryFn: () => getWorkList(searchParams),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteWork,
    onSuccess: () => {
      message.success('删除成功')
      queryClient.invalidateQueries({ queryKey: ['works'] })
    },
    onError: () => {
      message.error('删除失败')
    },
  })

  const columns = [
    {
      title: '封面',
      dataIndex: 'cover',
      width: 80,
      render: (cover: string) =>
        cover ? (
          <Image src={cover} width={60} height={80} style={{ objectFit: 'cover' }} />
        ) : (
          <div style={{ width: 60, height: 80, background: '#f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
            无封面
          </div>
        ),
    },
    {
      title: '标题',
      dataIndex: 'title',
      render: (title: string, record: Work) => (
        <div>
          <div style={{ fontWeight: 500 }}>{title}</div>
          {record.title_en && (
            <div style={{ fontSize: 12, color: '#666' }}>{record.title_en}</div>
          )}
        </div>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 100,
      render: (type: string) => {
        const config = workTypeMap[type] || { color: 'default', text: type }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '年份',
      dataIndex: 'year',
      width: 80,
      sorter: true,
    },
    {
      title: '评分',
      dataIndex: 'rating',
      width: 120,
      render: (rating: number) =>
        rating ? <Rate disabled defaultValue={rating / 2} allowHalf /> : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => {
        const config = statusMap[status] || { color: 'default', text: status }
        return <Tag color={config.color}>{config.text}</Tag>
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
      width: 200,
      fixed: 'right' as const,
      render: (_: unknown, record: Work) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/admin/works/${record.id}`)}
          >
            查看
          </Button>
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => navigate(`/admin/works/${record.id}/edit`)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除作品？"
            description="删除后不可恢复，是否继续？"
            onConfirm={() => deleteMutation.mutate(record.id)}
            okText="确认"
            cancelText="取消"
          >
            <Button type="text" danger size="small" icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 24,
        }}
      >
        <h2 style={{ margin: 0 }}>作品管理</h2>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/admin/works/new')}
        >
          新增作品
        </Button>
      </div>

      <Card style={{ marginBottom: 24 }}>
        <Space wrap>
          <Input.Search
            placeholder="搜索作品标题"
            allowClear
            enterButton={
              <>
                <SearchOutlined /> 搜索
              </>
            }
            onSearch={(value) =>
              setSearchParams((prev) => ({ ...prev, q: value, page: 1 }))
            }
            style={{ width: 300 }}
          />
          <Select
            placeholder="类型筛选"
            allowClear
            style={{ width: 150 }}
            onChange={(value) =>
              setSearchParams((prev) => ({ ...prev, type: value, page: 1 }))
            }
          >
            <Option value="movie">电影</Option>
            <Option value="tv">电视剧</Option>
            <Option value="album">专辑</Option>
            <Option value="single">单曲</Option>
            <Option value="book">书籍</Option>
          </Select>
          <Select
            placeholder="年份筛选"
            allowClear
            style={{ width: 120 }}
            onChange={(value) =>
              setSearchParams((prev) => ({ ...prev, year: value, page: 1 }))
            }
          >
            {Array.from({ length: 30 }, (_, i) => 2026 - i).map((year) => (
              <Option key={year} value={year}>
                {year}
              </Option>
            ))}
          </Select>
        </Space>
      </Card>

      <Table
        columns={columns}
        dataSource={data?.data?.items || []}
        rowKey="id"
        loading={isLoading}
        scroll={{ x: 1000 }}
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
