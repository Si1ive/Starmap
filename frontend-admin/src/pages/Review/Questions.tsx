import { useState } from 'react'
import { Card, Table, Button, Select, Space, Tag, Input, message, Descriptions, Drawer } from 'antd'
import { CheckOutlined, CloseOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listQuestionReviews, reviewQuestion, getSubjects } from '@/api'

const { TextArea } = Input

const reviewStatusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'orange', text: '待审核' }, approved: { color: 'green', text: '已通过' }, rejected: { color: 'red', text: '已拒绝' },
}
const difficultyConfig: Record<string, { color: string; text: string }> = {
  easy: { color: 'green', text: '简单' }, medium: { color: 'orange', text: '中等' }, hard: { color: 'red', text: '困难' },
}
const questionTypeConfig: Record<string, string> = {
  choice: '选择题', fill: '填空题', judge: '判断题', short_answer: '简答题', design: '设计题', analysis: '分析题',
}

const QuestionReviewPage = () => {
  const queryClient = useQueryClient()
  const [params, setParams] = useState<{ page: number; page_size: number; review_status?: string; subject_id?: string; question_type?: string }>({
    page: 1, page_size: 20, review_status: 'pending',
  })
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [currentItem, setCurrentItem] = useState<any>(null)
  const [reviewNotes, setReviewNotes] = useState('')

  const { data, isLoading } = useQuery({ queryKey: ['questionReviews', params], queryFn: () => listQuestionReviews(params) })
  const { data: subjectsData } = useQuery({ queryKey: ['subjects'], queryFn: getSubjects })

  const reviewMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      reviewQuestion(id, { review_status: status, review_notes: reviewNotes || undefined }),
    onSuccess: () => {
      message.success('操作成功')
      setDrawerOpen(false); setCurrentItem(null); setReviewNotes('')
      queryClient.invalidateQueries({ queryKey: ['questionReviews'] })
    },
  })

  const items = data?.data?.items || []
  const total = data?.data?.total || 0
  const subjects = subjectsData?.data || []

  const columns = [
    { title: '题干', dataIndex: 'content', key: 'content', ellipsis: true, render: (t: string) => t?.slice(0, 120) || '-' },
    { title: '题型', dataIndex: 'type', key: 'type', width: 100, render: (t: string) => questionTypeConfig[t] || t },
    { title: '难度', dataIndex: 'difficulty', key: 'difficulty', width: 80, render: (d: string) => <Tag color={difficultyConfig[d]?.color}>{difficultyConfig[d]?.text || d}</Tag> },
    { title: '来源', dataIndex: 'source', key: 'source', width: 120, ellipsis: true },
    { title: '状态', dataIndex: 'review_status', key: 'review_status', width: 100, render: (s: string) => <Tag color={reviewStatusConfig[s]?.color}>{reviewStatusConfig[s]?.text || s}</Tag> },
    { title: '操作', key: 'actions', width: 100, render: (_: any, record: any) => (
      <Button type="link" size="small" onClick={() => { setCurrentItem(record); setReviewNotes(record.review_notes || ''); setDrawerOpen(true) }}>审核</Button>
    )},
  ]

  return (
    <div>
      <h3><QuestionCircleOutlined style={{ marginRight: 8 }} />题目审核</h3>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select value={params.review_status || 'all'} style={{ width: 130 }}
            onChange={(v) => setParams((p) => ({ ...p, review_status: v === 'all' ? undefined : v, page: 1 }))}
            options={[{ label: '全部状态', value: 'all' }, { label: '待审核', value: 'pending' }, { label: '已通过', value: 'approved' }, { label: '已拒绝', value: 'rejected' }]}
          />
          <Select value={params.subject_id || 'all'} style={{ width: 150 }}
            onChange={(v) => setParams((p) => ({ ...p, subject_id: v === 'all' ? undefined : v, page: 1 }))}
            options={[{ label: '全部学科', value: 'all' }, ...subjects.map((s: any) => ({ label: s.name, value: s.id }))]}
          />
          <Select value={params.question_type || 'all'} style={{ width: 120 }}
            onChange={(v) => setParams((p) => ({ ...p, question_type: v === 'all' ? undefined : v, page: 1 }))}
            options={[{ label: '全部题型', value: 'all' }, ...Object.entries(questionTypeConfig).map(([k, v]) => ({ label: v, value: k }))]}
          />
        </Space>
      </Card>
      <Card>
        <Table dataSource={items} columns={columns} rowKey="id" loading={isLoading}
          pagination={{ current: params.page, total, pageSize: params.page_size, showTotal: (c) => `共 ${c} 条`, onChange: (page) => setParams((p) => ({ ...p, page })) }}
        />
      </Card>
      <Drawer title="审核题目" open={drawerOpen} onClose={() => setDrawerOpen(false)} width={600}
        extra={<Space>
          <Button danger icon={<CloseOutlined />} loading={reviewMut.isPending} onClick={() => reviewMut.mutate({ id: currentItem?.id, status: 'rejected' })}>拒绝</Button>
          <Button type="primary" icon={<CheckOutlined />} loading={reviewMut.isPending} onClick={() => reviewMut.mutate({ id: currentItem?.id, status: 'approved' })}>通过</Button>
        </Space>}
      >
        {currentItem && (
          <div>
            <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="题型">{questionTypeConfig[currentItem.type] || currentItem.type}</Descriptions.Item>
              <Descriptions.Item label="题干"><div style={{ maxHeight: 150, overflow: 'auto' }}>{currentItem.content}</div></Descriptions.Item>
              <Descriptions.Item label="难度"><Tag color={difficultyConfig[currentItem.difficulty]?.color}>{difficultyConfig[currentItem.difficulty]?.text}</Tag></Descriptions.Item>
              <Descriptions.Item label="来源">{currentItem.source || '-'}</Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={reviewStatusConfig[currentItem.review_status]?.color}>{reviewStatusConfig[currentItem.review_status]?.text}</Tag></Descriptions.Item>
            </Descriptions>
            <div style={{ marginBottom: 8 }}><strong>审核备注</strong></div>
            <TextArea rows={3} value={reviewNotes} onChange={(e) => setReviewNotes(e.target.value)} placeholder="可选" />
          </div>
        )}
      </Drawer>
    </div>
  )
}

export default QuestionReviewPage
