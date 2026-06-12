import { useState } from 'react'
import { Card, Table, Button, Select, Space, Tag, Input, message, Descriptions, Drawer } from 'antd'
import { CheckOutlined, CloseOutlined, BookOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listKnowledgeReviews, reviewKnowledgePoint, getSubjects, getChapters } from '@/api'

const { TextArea } = Input

const reviewStatusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'orange', text: '待审核' },
  approved: { color: 'green', text: '已通过' },
  rejected: { color: 'red', text: '已拒绝' },
}
const difficultyConfig: Record<string, { color: string; text: string }> = {
  easy: { color: 'green', text: '简单' }, medium: { color: 'orange', text: '中等' }, hard: { color: 'red', text: '困难' },
}
const examFreqConfig: Record<string, { color: string; text: string }> = {
  high: { color: 'red', text: '高频' }, medium: { color: 'orange', text: '中频' }, low: { color: 'blue', text: '低频' }, never: { color: 'default', text: '未考' },
}

const KnowledgeReviewPage = () => {
  const queryClient = useQueryClient()
  const [params, setParams] = useState<{ page: number; page_size: number; review_status?: string; subject_id?: string; chapter_id?: string }>({
    page: 1, page_size: 20, review_status: 'pending',
  })
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [currentItem, setCurrentItem] = useState<any>(null)
  const [reviewNotes, setReviewNotes] = useState('')

  const { data, isLoading } = useQuery({ queryKey: ['knowledgeReviews', params], queryFn: () => listKnowledgeReviews(params) })
  const { data: subjectsData } = useQuery({ queryKey: ['subjects'], queryFn: getSubjects })
  const { data: chaptersData } = useQuery({
    queryKey: ['chapters', params.subject_id],
    queryFn: () => getChapters(params.subject_id!),
    enabled: !!params.subject_id,
  })

  const reviewMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      reviewKnowledgePoint(id, { review_status: status, review_notes: reviewNotes || undefined }),
    onSuccess: () => {
      message.success('操作成功')
      setDrawerOpen(false); setCurrentItem(null); setReviewNotes('')
      queryClient.invalidateQueries({ queryKey: ['knowledgeReviews'] })
    },
  })

  const items = data?.data?.items || []
  const total = data?.data?.total || 0
  const subjects = subjectsData?.data || []
  const chapters = chaptersData?.data || []

  const columns = [
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true, render: (t: string) => <strong>{t}</strong> },
    { title: '内容预览', dataIndex: 'content', key: 'content', ellipsis: true, render: (t: string) => t?.slice(0, 100) || '-' },
    {
      title: '难度', dataIndex: 'difficulty', key: 'difficulty', width: 80,
      render: (d: string) => <Tag color={difficultyConfig[d]?.color}>{difficultyConfig[d]?.text || d}</Tag>,
    },
    {
      title: '考频', dataIndex: 'exam_frequency', key: 'exam_frequency', width: 80,
      render: (f: string) => <Tag color={examFreqConfig[f]?.color}>{examFreqConfig[f]?.text || f}</Tag>,
    },
    {
      title: '状态', dataIndex: 'review_status', key: 'review_status', width: 100,
      render: (s: string) => <Tag color={reviewStatusConfig[s]?.color}>{reviewStatusConfig[s]?.text || s}</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_: any, record: any) => (
        <Button type="link" size="small" onClick={() => { setCurrentItem(record); setReviewNotes(record.review_notes || ''); setDrawerOpen(true) }}>审核</Button>
      ),
    },
  ]

  return (
    <div>
      <h3><BookOutlined style={{ marginRight: 8 }} />知识点审核</h3>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select value={params.review_status || 'all'} style={{ width: 130 }}
            onChange={(v) => setParams((p) => ({ ...p, review_status: v === 'all' ? undefined : v, page: 1 }))}
            options={[{ label: '全部状态', value: 'all' }, { label: '待审核', value: 'pending' }, { label: '已通过', value: 'approved' }, { label: '已拒绝', value: 'rejected' }]}
          />
          <Select value={params.subject_id || 'all'} style={{ width: 150 }}
            onChange={(v) => setParams((p) => ({ ...p, subject_id: v === 'all' ? undefined : v, chapter_id: undefined, page: 1 }))}
            options={[{ label: '全部学科', value: 'all' }, ...subjects.map((s: any) => ({ label: s.name, value: s.id }))]}
          />
          {params.subject_id && chapters.length > 0 && (
            <Select value={params.chapter_id || 'all'} style={{ width: 150 }}
              onChange={(v) => setParams((p) => ({ ...p, chapter_id: v === 'all' ? undefined : v, page: 1 }))}
              options={[{ label: '全部章节', value: 'all' }, ...chapters.map((c: any) => ({ label: c.name, value: c.id }))]}
            />
          )}
        </Space>
      </Card>
      <Card>
        <Table dataSource={items} columns={columns} rowKey="id" loading={isLoading}
          pagination={{ current: params.page, total, pageSize: params.page_size, showTotal: (c) => `共 ${c} 条`, onChange: (page) => setParams((p) => ({ ...p, page })) }}
        />
      </Card>
      <Drawer title="审核知识点" open={drawerOpen} onClose={() => setDrawerOpen(false)} width={600}
        extra={<Space>
          <Button danger icon={<CloseOutlined />} loading={reviewMut.isPending} onClick={() => reviewMut.mutate({ id: currentItem?.id, status: 'rejected' })}>拒绝</Button>
          <Button type="primary" icon={<CheckOutlined />} loading={reviewMut.isPending} onClick={() => reviewMut.mutate({ id: currentItem?.id, status: 'approved' })}>通过</Button>
        </Space>}
      >
        {currentItem && (
          <div>
            <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="标题">{currentItem.title}</Descriptions.Item>
              <Descriptions.Item label="内容"><div style={{ maxHeight: 200, overflow: 'auto' }}>{currentItem.content}</div></Descriptions.Item>
              <Descriptions.Item label="难度"><Tag color={difficultyConfig[currentItem.difficulty]?.color}>{difficultyConfig[currentItem.difficulty]?.text}</Tag></Descriptions.Item>
              <Descriptions.Item label="考频"><Tag color={examFreqConfig[currentItem.exam_frequency]?.color}>{examFreqConfig[currentItem.exam_frequency]?.text}</Tag></Descriptions.Item>
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

export default KnowledgeReviewPage
