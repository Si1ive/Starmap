import { useState } from 'react'
import { Card, Table, Button, Select, Space, Tag, Input, message, Descriptions, Drawer, Typography, Modal, Popconfirm } from 'antd'
import { CheckOutlined, CloseOutlined, ApartmentOutlined, DeleteOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listChapterRelations, reviewChapterRelation, deleteChapterRelation, batchDeleteChapterRelations } from '@/api/chapter-relation'

const { TextArea } = Input
const { Text } = Typography

const reviewStatusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'orange', text: '待审核' },
  approved: { color: 'green', text: '已通过' },
  rejected: { color: 'red', text: '已拒绝' },
}

const sourceTypeConfig: Record<string, { color: string; text: string }> = {
  llm: { color: 'blue', text: 'LLM 标注' },
  embedding: { color: 'purple', text: '语义相似度' },
  manual: { color: 'green', text: '人工' },
}

const relationTypeConfig: Record<string, { color: string; text: string }> = {
  similar_to: { color: 'cyan', text: '相似考点' },
  prerequisite: { color: 'blue', text: '前置知识' },
  contrast_with: { color: 'volcano', text: '对比考点' },
  common_confusion: { color: 'magenta', text: '易混淆' },
}

const ChapterRelationReviewPage = () => {
  const queryClient = useQueryClient()
  const [params, setParams] = useState<{
    page: number; page_size: number; review_status?: string; relation_type?: string; source_type?: string
  }>({
    page: 1, page_size: 20, review_status: 'pending',
  })
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [currentItem, setCurrentItem] = useState<any>(null)
  const [reviewNotes, setReviewNotes] = useState('')
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const { data, isLoading } = useQuery({
    queryKey: ['chapterRelationReviews', params],
    queryFn: () => listChapterRelations(params),
  })

  const reviewMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      reviewChapterRelation(id, { review_status: status, review_notes: reviewNotes || undefined }),
    onSuccess: () => {
      message.success('操作成功')
      setDrawerOpen(false); setCurrentItem(null); setReviewNotes('')
      queryClient.invalidateQueries({ queryKey: ['chapterRelationReviews'] })
    },
  })

  const deleteMut = useMutation({
    mutationFn: deleteChapterRelation,
    onSuccess: (_, id) => {
      message.success('删除成功')
      if (currentItem?.id === id) {
        setDrawerOpen(false)
        setCurrentItem(null)
        setReviewNotes('')
      }
      queryClient.invalidateQueries({ queryKey: ['chapterRelationReviews'] })
    },
  })

  const batchDeleteMut = useMutation({
    mutationFn: batchDeleteChapterRelations,
    onSuccess: (res) => {
      message.success(`已删除 ${res.data?.deleted_count || 0} 条考点关联`)
      setSelectedRowKeys([])
      if (currentItem && selectedRowKeys.includes(currentItem.id)) {
        setDrawerOpen(false)
        setCurrentItem(null)
        setReviewNotes('')
      }
      queryClient.invalidateQueries({ queryKey: ['chapterRelationReviews'] })
    },
  })

  const items = data?.data?.items || []
  const total = data?.data?.total || 0

  const columns = [
    {
      title: '源考点', dataIndex: 'source_chapter_name', key: 'source', ellipsis: true,
      render: (t: string) => <strong>{t}</strong>,
    },
    {
      title: '关系', key: 'arrow', width: 100,
      render: (_: any, record: any) => {
        const cfg = relationTypeConfig[record.relation_type] || { color: 'default', text: record.relation_type }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    {
      title: '目标考点', dataIndex: 'target_chapter_name', key: 'target', ellipsis: true,
      render: (t: string) => <strong>{t}</strong>,
    },
    {
      title: '来源', dataIndex: 'source_type', key: 'source_type', width: 110,
      render: (s: string) => {
        const cfg = sourceTypeConfig[s] || { color: 'default', text: s }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    {
      title: '关联证据', dataIndex: 'evidence_text', key: 'evidence_text', ellipsis: true,
      render: (t: string) => t?.slice(0, 80) || '-',
    },
    {
      title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 80,
      render: (v: number) => v != null ? `${(v * 100).toFixed(0)}%` : '-',
    },
    {
      title: '状态', dataIndex: 'review_status', key: 'review_status', width: 90,
      render: (s: string) => <Tag color={reviewStatusConfig[s]?.color}>{reviewStatusConfig[s]?.text || s}</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 120,
      render: (_: any, record: any) => (
        <Space size="small">
          <Button type="link" size="small"
            onClick={() => { setCurrentItem(record); setReviewNotes(record.review_notes || ''); setDrawerOpen(true) }}
          >审核</Button>
          <Popconfirm title="确定删除这条考点关联？" onConfirm={() => deleteMut.mutate(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) return
    Modal.confirm({
      title: '确认批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 条考点关联吗？`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => batchDeleteMut.mutate(selectedRowKeys.map(String)),
    })
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}><ApartmentOutlined style={{ marginRight: 8 }} />考点关联审核</h3>
        <Button
          danger
          icon={<DeleteOutlined />}
          disabled={selectedRowKeys.length === 0}
          loading={batchDeleteMut.isPending}
          onClick={handleBatchDelete}
        >
          批量删除{selectedRowKeys.length ? ` (${selectedRowKeys.length})` : ''}
        </Button>
      </div>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        审核 LLM 标注和 embedding 相似度发现的跨章节考点关联。通过后的关联将用于检索时的跨章扩展。
      </Text>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select value={params.review_status || 'all'} style={{ width: 130 }}
            onChange={(v) => setParams((p) => ({ ...p, review_status: v === 'all' ? undefined : v, page: 1 }))}
            options={[{ label: '全部状态', value: 'all' }, { label: '待审核', value: 'pending' }, { label: '已通过', value: 'approved' }, { label: '已拒绝', value: 'rejected' }]}
          />
          <Select value={params.relation_type || 'all'} style={{ width: 140 }}
            onChange={(v) => setParams((p) => ({ ...p, relation_type: v === 'all' ? undefined : v, page: 1 }))}
            options={[{ label: '全部关系类型', value: 'all' }, ...Object.entries(relationTypeConfig).map(([k, v]) => ({ label: v.text, value: k }))]}
          />
          <Select value={params.source_type || 'all'} style={{ width: 140 }}
            onChange={(v) => setParams((p) => ({ ...p, source_type: v === 'all' ? undefined : v, page: 1 }))}
            options={[{ label: '全部来源', value: 'all' }, ...Object.entries(sourceTypeConfig).map(([k, v]) => ({ label: v.text, value: k }))]}
          />
        </Space>
      </Card>

      <Card>
        <Table dataSource={items} columns={columns} rowKey="id" loading={isLoading}
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            preserveSelectedRowKeys: true,
          }}
          pagination={{
            current: params.page, total, pageSize: params.page_size,
            showTotal: (c) => `共 ${c} 条`,
            onChange: (page) => setParams((p) => ({ ...p, page })),
          }}
        />
      </Card>

      <Drawer title="审核考点关联" open={drawerOpen} onClose={() => setDrawerOpen(false)} width={550}
        extra={<Space>
          <Button danger icon={<CloseOutlined />} loading={reviewMut.isPending}
            onClick={() => reviewMut.mutate({ id: currentItem?.id, status: 'rejected' })}
          >拒绝</Button>
          <Button type="primary" icon={<CheckOutlined />} loading={reviewMut.isPending}
            onClick={() => reviewMut.mutate({ id: currentItem?.id, status: 'approved' })}
          >通过</Button>
        </Space>}
      >
        {currentItem && (
          <div>
            <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="源考点">
                {currentItem.source_chapter_name}
              </Descriptions.Item>
              <Descriptions.Item label="目标考点">
                {currentItem.target_chapter_name}
              </Descriptions.Item>
              <Descriptions.Item label="关系类型">
                <Tag color={relationTypeConfig[currentItem.relation_type]?.color}>
                  {relationTypeConfig[currentItem.relation_type]?.text || currentItem.relation_type}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="来源">
                <Tag color={sourceTypeConfig[currentItem.source_type]?.color}>
                  {sourceTypeConfig[currentItem.source_type]?.text || currentItem.source_type}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="置信度">
                {currentItem.confidence != null ? `${(currentItem.confidence * 100).toFixed(0)}%` : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="关联证据">
                <div style={{ maxHeight: 120, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                  {currentItem.evidence_text || '-'}
                </div>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={reviewStatusConfig[currentItem.review_status]?.color}>
                  {reviewStatusConfig[currentItem.review_status]?.text}
                </Tag>
              </Descriptions.Item>
              {currentItem.review_notes && (
                <Descriptions.Item label="审核备注">{currentItem.review_notes}</Descriptions.Item>
              )}
            </Descriptions>

            <div style={{ marginBottom: 8 }}><strong>审核备注</strong></div>
            <TextArea rows={3} value={reviewNotes} onChange={(e) => setReviewNotes(e.target.value)}
              placeholder="可选，审核理由或修正说明"
            />
          </div>
        )}
      </Drawer>
    </div>
  )
}

export default ChapterRelationReviewPage
