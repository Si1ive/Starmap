import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Table, Tag, Button, Select, Space } from 'antd'
import { EyeOutlined, EditOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getQuestions, getSubjects, getChapters } from '@/api'
import type { Question } from '@/types'

const typeConfig: Record<string, { color: string; text: string }> = {
  choice: { color: 'blue', text: '选择题' },
  fill: { color: 'green', text: '填空题' },
  judge: { color: 'orange', text: '判断题' },
  short_answer: { color: 'purple', text: '简答题' },
  design: { color: 'red', text: '设计题' },
  analysis: { color: 'cyan', text: '分析题' },
}

const difficultyConfig: Record<string, { color: string; text: string }> = {
  easy: { color: 'green', text: '简单' },
  medium: { color: 'orange', text: '中等' },
  hard: { color: 'red', text: '困难' },
}

const QuestionList = () => {
  const navigate = useNavigate()
  const [params, setParams] = useState<{
    page: number
    page_size: number
    subject_id?: string
    chapter_id?: string
    type?: string
    difficulty?: string
  }>({ page: 1, page_size: 20 })

  const { data, isLoading } = useQuery({
    queryKey: ['questions', params],
    queryFn: () => getQuestions(params),
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

  const questions = data?.data?.items || []
  const total = data?.data?.total || 0
  const subjects = subjectsData?.data || []
  const chapters = chaptersData?.data || []

  const columns = [
    {
      title: '题目',
      dataIndex: 'content',
      width: 300,
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
      title: '题型',
      dataIndex: 'type',
      width: 100,
      render: (t: string) => {
        const config = typeConfig[t] || { color: 'default', text: t }
        return <Tag color={config.color}>{config.text}</Tag>
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
      title: '来源',
      dataIndex: 'source',
      width: 150,
      ellipsis: true,
    },
    {
      title: '年份',
      dataIndex: 'exam_year',
      width: 80,
      render: (y: number) => (y > 0 ? y : '-'),
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
      render: (_: unknown, record: Question) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/admin/questions/${record.id}`)}
          >
            查看
          </Button>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => navigate(`/admin/questions/${record.id}/edit`)}
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
        <h2 style={{ margin: 0 }}>题目管理</h2>
      </div>

      <Card>
        <Space wrap style={{ marginBottom: 16 }}>
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
            value={params.type || 'all'}
            style={{ width: 120 }}
            onChange={(value) =>
              setParams((prev) => ({ ...prev, page: 1, type: value === 'all' ? undefined : value }))
            }
            options={[
              { label: '全部题型', value: 'all' },
              { label: '选择题', value: 'choice' },
              { label: '填空题', value: 'fill' },
              { label: '判断题', value: 'judge' },
              { label: '简答题', value: 'short_answer' },
              { label: '设计题', value: 'design' },
              { label: '分析题', value: 'analysis' },
            ]}
          />
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
          dataSource={questions as any[]}
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

export default QuestionList
