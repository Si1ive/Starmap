import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Card, Table, Tag, Button, Input, Select, Space, Modal, message } from 'antd'
import { AuditOutlined, DeleteOutlined, EyeOutlined, EditOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  batchDeleteQuestions,
  getQuestions,
  getSubjects,
  getChapters,
  reviewQuestion,
} from '@/api'
import ContentReviewDrawer, {
  ReviewStatusTag,
  type ReviewStatus,
} from '@/components/ContentReviewDrawer'
import type { QuestionListParams } from '@/api/question'
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

const parseReviewStatus = (value: string | null): ReviewStatus | undefined =>
  value === 'pending' || value === 'approved' || value === 'rejected' ? value : undefined

const QuestionList = () => {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [reviewItem, setReviewItem] = useState<Question | null>(null)
  const [params, setParams] = useState<QuestionListParams>(() => ({
    page: 1,
    page_size: 20,
    review_status: parseReviewStatus(searchParams.get('review_status')),
  }))

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
    queryFn: () => getChapters(params.subject_id || ''),
    enabled: !!params.subject_id,
  })

  const questions = data?.data?.items || []
  const total = data?.data?.total || 0
  const subjects = subjectsData?.data || []
  const chapters = chaptersData?.data || []

  const batchDeleteMutation = useMutation({
    mutationFn: batchDeleteQuestions,
    onSuccess: (res) => {
      message.success(`已删除 ${res.data?.deleted_count || 0} 道题目`)
      setSelectedRowKeys([])
      queryClient.invalidateQueries({ queryKey: ['questions'] })
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      message.error(typeof detail === 'string' ? detail : '删除失败')
    },
  })

  const reviewMutation = useMutation({
    mutationFn: ({
      id,
      reviewStatus,
      reviewNotes,
      primaryChapterId,
    }: {
      id: string
      reviewStatus: 'approved' | 'rejected'
      reviewNotes?: string
      primaryChapterId?: string
    }) =>
      reviewQuestion(id, {
        review_status: reviewStatus,
        review_notes: reviewNotes,
        primary_chapter_id: primaryChapterId,
      }),
    onSuccess: (_, variables) => {
      message.success(variables.reviewStatus === 'approved' ? '人工核验已通过' : '已标记为未通过')
      setReviewItem(null)
      queryClient.invalidateQueries({ queryKey: ['questions'] })
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      message.error(typeof detail === 'string' ? detail : '审核保存失败')
    },
  })

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) return
    Modal.confirm({
      title: '确认批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 道题目吗？删除后列表和检索中将不再展示。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => batchDeleteMutation.mutate(selectedRowKeys.map(String)),
    })
  }

  const handleReviewStatusChange = (value: string) => {
    const reviewStatus = value === 'all' ? undefined : (value as ReviewStatus)
    setParams((prev) => ({ ...prev, page: 1, review_status: reviewStatus }))

    const nextSearchParams = new URLSearchParams(searchParams)
    if (reviewStatus) {
      nextSearchParams.set('review_status', reviewStatus)
    } else {
      nextSearchParams.delete('review_status')
    }
    setSearchParams(nextSearchParams, { replace: true })
  }

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
      title: '使用状态',
      dataIndex: 'status',
      width: 100,
      render: (s: string) => (
        <Tag color={s === 'active' ? 'green' : 'default'}>
          {s === 'active' ? '使用中' : '已停用'}
        </Tag>
      ),
    },
    {
      title: '人工核验',
      dataIndex: 'review_status',
      width: 110,
      render: (status: string) => <ReviewStatusTag status={status} />,
    },
    {
      title: '操作',
      key: 'action',
      width: 210,
      fixed: 'right' as const,
      render: (_: unknown, record: Question) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<AuditOutlined />}
            onClick={() => setReviewItem(record)}
          >
            审核
          </Button>
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
        <Button
          danger
          icon={<DeleteOutlined />}
          disabled={selectedRowKeys.length === 0}
          loading={batchDeleteMutation.isPending}
          onClick={handleBatchDelete}
        >
          批量删除{selectedRowKeys.length ? ` (${selectedRowKeys.length})` : ''}
        </Button>
      </div>

      <Card>
        <Space wrap style={{ marginBottom: 16 }}>
          <Input.Search
            placeholder="搜索题干"
            style={{ width: 220 }}
            allowClear
            onSearch={(value) =>
              setParams((prev) => ({ ...prev, page: 1, keyword: value.trim() || undefined }))
            }
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
          <Select
            value={params.status || 'all'}
            style={{ width: 120 }}
            onChange={(value) =>
              setParams((prev) => ({ ...prev, page: 1, status: value === 'all' ? undefined : value }))
            }
            options={[
              { label: '全部使用状态', value: 'all' },
              { label: '使用中', value: 'active' },
              { label: '已停用', value: 'pending' },
            ]}
          />
          <Select
            value={params.review_status || 'all'}
            style={{ width: 140 }}
            onChange={handleReviewStatusChange}
            options={[
              { label: '全部人工核验', value: 'all' },
              { label: '待人工核验', value: 'pending' },
              { label: '已通过', value: 'approved' },
              { label: '未通过', value: 'rejected' },
            ]}
          />
        </Space>

        <Table
          columns={columns}
          dataSource={questions as any[]}
          rowKey="id"
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            preserveSelectedRowKeys: true,
          }}
          loading={isLoading}
          size="small"
          scroll={{ x: 1450 }}
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

      <ContentReviewDrawer
        open={!!reviewItem}
        title="题目人工核验"
        item={reviewItem}
        submitting={reviewMutation.isPending}
        onClose={() => setReviewItem(null)}
        onSubmit={(review) => {
          if (!reviewItem) return
          reviewMutation.mutate({
            id: reviewItem.id,
            reviewStatus: review.review_status,
            reviewNotes: review.review_notes,
            primaryChapterId: review.primary_chapter_id,
          })
        }}
        details={
          reviewItem
            ? [
                {
                  key: 'type',
                  label: '题型',
                  content: typeConfig[reviewItem.type]?.text || reviewItem.type,
                },
                {
                  key: 'content',
                  label: '题干',
                  content: <div style={{ maxHeight: 180, overflow: 'auto' }}>{reviewItem.content}</div>,
                },
                {
                  key: 'difficulty',
                  label: '难度',
                  content: (
                    <Tag color={difficultyConfig[reviewItem.difficulty]?.color}>
                      {difficultyConfig[reviewItem.difficulty]?.text || reviewItem.difficulty}
                    </Tag>
                  ),
                },
                { key: 'source', label: '来源', content: reviewItem.source || '-' },
              ]
            : []
        }
      />
    </div>
  )
}

export default QuestionList
