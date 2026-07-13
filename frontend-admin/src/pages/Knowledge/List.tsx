import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Card, Table, Tag, Button, Input, Select, Space, Modal, message } from 'antd'
import { AuditOutlined, DeleteOutlined, EyeOutlined, EditOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  batchDeleteKnowledgePoints,
  getKnowledgePoints,
  getSubjects,
  getChapters,
  reviewKnowledgePoint,
} from '@/api'
import ContentReviewDrawer, {
  ReviewStatusTag,
  type ReviewStatus,
} from '@/components/ContentReviewDrawer'
import type { KnowledgePointListParams } from '@/api/knowledge'
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

const parseReviewStatus = (value: string | null): ReviewStatus | undefined =>
  value === 'pending' || value === 'approved' || value === 'rejected' ? value : undefined

const KnowledgeList = () => {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [reviewItem, setReviewItem] = useState<KnowledgePoint | null>(null)
  const [params, setParams] = useState<KnowledgePointListParams>(() => ({
    page: 1,
    page_size: 20,
    review_status: parseReviewStatus(searchParams.get('review_status')),
  }))

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
    queryFn: () => getChapters(params.subject_id || ''),
    enabled: !!params.subject_id,
  })

  const points = data?.data?.items || []
  const total = data?.data?.total || 0
  const subjects = subjectsData?.data || []
  const chapters = chaptersData?.data || []

  const batchDeleteMutation = useMutation({
    mutationFn: batchDeleteKnowledgePoints,
    onSuccess: (res) => {
      if (res.data?.indexing?.status === 'warning') {
        message.warning(`已删除 ${res.data.deleted_count} 个知识点，但旧向量清理失败`)
      } else {
        message.success(`已删除 ${res.data?.deleted_count || 0} 个知识点`)
      }
      setSelectedRowKeys([])
      queryClient.invalidateQueries({ queryKey: ['knowledgePoints'] })
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
      reviewKnowledgePoint(id, {
        review_status: reviewStatus,
        review_notes: reviewNotes,
        primary_chapter_id: primaryChapterId,
      }),
    onSuccess: (res, variables) => {
      const indexingStatus = res.data?.indexing?.status
      if (indexingStatus === 'failed') {
        message.warning('人工核验已保存，但检索索引更新失败，可稍后重试')
      } else if (indexingStatus === 'warning') {
        message.warning('人工核验和新索引已保存，但旧向量清理失败')
      } else {
        message.success(variables.reviewStatus === 'approved' ? '人工核验已通过' : '已标记为未通过')
      }
      setReviewItem(null)
      queryClient.invalidateQueries({ queryKey: ['knowledgePoints'] })
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
      content: `确定要删除选中的 ${selectedRowKeys.length} 个知识点吗？删除后列表和检索中将不再展示。`,
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
      render: (_: unknown, record: KnowledgePoint) => (
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
          dataSource={points as any[]}
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
        title="知识点人工核验"
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
                { key: 'title', label: '标题', content: reviewItem.title },
                {
                  key: 'content',
                  label: '内容',
                  content: <div style={{ maxHeight: 220, overflow: 'auto' }}>{reviewItem.content}</div>,
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
                {
                  key: 'examFrequency',
                  label: '考频',
                  content: (
                    <Tag color={examFreqConfig[reviewItem.exam_frequency]?.color}>
                      {examFreqConfig[reviewItem.exam_frequency]?.text || reviewItem.exam_frequency}
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

export default KnowledgeList
