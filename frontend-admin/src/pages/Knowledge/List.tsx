import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Table, Tag, Button, Input, Select, Space } from 'antd'
import { EyeOutlined, EditOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getKnowledgePoints, getSubjects, getChapters } from '@/api'
import type { KnowledgePoint } from '@/types'

const difficultyConfig: Record<string, { color: string; text: string }> = {
  easy: { color: 'green', text: '简单' },
  medium: { color: 'orange', text: '中等' },
  hard: { color: 'red', text: '困难' },
}

const examFreqConfig: Record<string, { color: string; text: string }> = {
  high: { color: 'red', text: '高频' },
  medium: { color: 'orange', text: '中频' },
  low: { color: 'blue', text: '低频' },
  never: { color: 'default', text: '未考' },
}

const KnowledgeList = () => {
  const navigate = useNavigate()
  const [params, setParams] = useState<{
    page: number
    page_size: number
    subject_id?: string
    chapter_id?: string
    difficulty?: string
    keyword?: string
  }>({ page: 1, page_size: 20 })

  const { data, isLoading } = useQuery({
    queryKey: ['knowledgePoints', params],
    queryFn: () => getKnowledgePoints(params),
  })

  const { data: subjectsData } = useQuery({
    queryKey: ['subjects'],
    queryFn: getSubjects,
  })

  const { data: chaptersData } = useQuery({
    queryKey: ['chapters', params.subject_id],
    queryFn: () => getChapters(params.subject_id!),
    enabled: !!params.subject_id,
  })

  const points = data?.data?.items || []
  const total = data?.data?.total || 0
  const subjects = subjectsData?.data || []
  const chapters = chaptersData?.data || []

  const columns = [
    {
      title: '标题',
      dataIndex: 'title',
      width: 250,
      ellipsis: true,
    },
    {
      title: '学科',
      dataIndex: 'subject_id',
      width: 120,
      render: (subjectId: string) => {
        const subject = subjects.find((s) => s.id === subjectId)
        return subject?.name || subjectId
      },
    },
    {
      title: '章节',
      dataIndex: 'chapter_id',
      width: 120,
      render: (chapterId: string) => {
        const chapter = chapters.find((c) => c.id === chapterId)
        return chapter?.name || chapterId
      },
    },
    {
      title: '难度',
      dataIndex: 'difficulty',
      width: 80,
      render: (d: string) => {
        const config = difficultyConfig[d] || { color: 'default', text: d }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '考频',
      dataIndex: 'exam_frequency',
      width: 80,
      render: (f: string) => {
        const config = examFreqConfig[f] || { color: 'default', text: f }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '来源',
      dataIndex: 'source',
      width: 150,
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (s: string) => (
        <Tag color={s === 'active' ? 'green' : 'default'}>
          {s === 'active' ? '已发布' : '待审核'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      fixed: 'right' as const,
      render: (_: unknown, record: KnowledgePoint) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/admin/knowledge/${record.id}`)}
          >
            查看
          </Button>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => navigate(`/admin/knowledge/${record.id}/edit`)}
          >
            编辑
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>知识点管理</h2>
      </div>

      <Card>
        <Space wrap style={{ marginBottom: 16 }}>
          <Input.Search
            placeholder="搜索知识点标题"
            style={{ width: 250 }}
            onSearch={(value) => setParams((prev) => ({ ...prev, page: 1, keyword: value || undefined }))}
            allowClear
          />
          <Select
            value={params.subject_id || 'all'}
            style={{ width: 150 }}
            onChange={(value) =>
              setParams((prev) => ({
                ...prev,
                page: 1,
                subject_id: value === 'all' ? undefined : value,
                chapter_id: undefined,
              }))
            }
            options={[
              { label: '全部学科', value: 'all' },
              ...subjects.map((s) => ({ label: s.name, value: s.id })),
            ]}
          />
          {params.subject_id && (
            <Select
              value={params.chapter_id || 'all'}
              style={{ width: 150 }}
              onChange={(value) =>
                setParams((prev) => ({ ...prev, page: 1, chapter_id: value === 'all' ? undefined : value }))
              }
              options={[
                { label: '全部章节', value: 'all' },
                ...chapters.map((c) => ({ label: c.name, value: c.id })),
              ]}
            />
          )}
          <Select
            value={params.difficulty || 'all'}
            style={{ width: 120 }}
            onChange={(value) =>
              setParams((prev) => ({ ...prev, page: 1, difficulty: value === 'all' ? undefined : value }))
            }
            options={[
              { label: '全部难度', value: 'all' },
              { label: '简单', value: 'easy' },
              { label: '中等', value: 'medium' },
              { label: '困难', value: 'hard' },
            ]}
          />
        </Space>

        <Table
          columns={columns}
          dataSource={points as any[]}
          rowKey="id"
          loading={isLoading}
          size="small"
          scroll={{ x: 1200 }}
          pagination={{
            current: params.page,
            pageSize: params.page_size,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
          }}
          onChange={(pagination) =>
            setParams((prev) => ({
              ...prev,
              page: pagination.current || 1,
              page_size: pagination.pageSize || 20,
            }))
          }
        />
      </Card>
    </div>
  )
}

export default KnowledgeList
