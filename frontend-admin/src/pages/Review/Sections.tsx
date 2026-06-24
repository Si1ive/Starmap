import { useState } from 'react'
import { Card, Table, Button, Select, Space, Tag, Input, message, Descriptions, Drawer, Modal, Popconfirm } from 'antd'
import { CheckOutlined, CloseOutlined, AuditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listSectionReviews, reviewSectionMapping, getSubjects, deleteSectionMapping, batchDeleteSectionMappings } from '@/api'

const { TextArea } = Input

const reviewStatusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'orange', text: '待审核' },
  approved: { color: 'green', text: '已通过' },
  rejected: { color: 'red', text: '已拒绝' },
}

const SectionReviewPage = () => {
  const queryClient = useQueryClient()
  const [params, setParams] = useState<{ page: number; page_size: number; review_status?: string; subject_id?: string }>({
    page: 1, page_size: 20, review_status: 'pending',
  })
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [currentItem, setCurrentItem] = useState<any>(null)
  const [reviewNotes, setReviewNotes] = useState('')
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const { data, isLoading } = useQuery({
    queryKey: ['sectionReviews', params],
    queryFn: () => listSectionReviews(params),
  })

  const { data: subjectsData } = useQuery({ queryKey: ['subjects'], queryFn: getSubjects })

  const reviewMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      reviewSectionMapping(id, { review_status: status, review_notes: reviewNotes || undefined }),
    onSuccess: (_, vars) => {
      message.success(vars.status === 'approved' ? '已通过' : '已拒绝')
      setDrawerOpen(false)
      setCurrentItem(null)
      setReviewNotes('')
      queryClient.invalidateQueries({ queryKey: ['sectionReviews'] })
    },
  })

  const deleteMut = useMutation({
    mutationFn: deleteSectionMapping,
    onSuccess: (_, id) => {
      message.success('删除成功')
      if (currentItem?.mapping_id === id) {
        setDrawerOpen(false)
        setCurrentItem(null)
        setReviewNotes('')
      }
      queryClient.invalidateQueries({ queryKey: ['sectionReviews'] })
    },
  })

  const batchDeleteMut = useMutation({
    mutationFn: batchDeleteSectionMappings,
    onSuccess: (res) => {
      message.success(`已删除 ${res.data?.deleted_count || 0} 条映射`)
      setSelectedRowKeys([])
      if (currentItem && selectedRowKeys.includes(currentItem.mapping_id)) {
        setDrawerOpen(false)
        setCurrentItem(null)
        setReviewNotes('')
      }
      queryClient.invalidateQueries({ queryKey: ['sectionReviews'] })
    },
  })

  const items = data?.data?.items || []
  const total = data?.data?.total || 0
  const subjects = subjectsData?.data || []

  const columns = [
    { title: '原生标题', dataIndex: 'section_title', key: 'section_title', ellipsis: true },
    { title: '映射章节', dataIndex: 'canonical_chapter_name', key: 'canonical_chapter_name' },
    {
      title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 100,
      sorter: (a: any, b: any) => a.confidence - b.confidence,
      render: (v: number) => {
        const pct = v ? (v * 100).toFixed(0) : '0'
        const color = v >= 0.9 ? 'green' : v >= 0.6 ? 'orange' : 'red'
        return <Tag color={color}>{pct}%</Tag>
      },
    },
    { title: '映射类型', dataIndex: 'mapping_type', key: 'mapping_type', width: 100 },
    {
      title: '状态', dataIndex: 'review_status', key: 'review_status', width: 100,
      render: (s: string) => <Tag color={reviewStatusConfig[s]?.color}>{reviewStatusConfig[s]?.text || s}</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 120,
      render: (_: any, record: any) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => { setCurrentItem(record); setReviewNotes(record.review_notes || ''); setDrawerOpen(true) }}>
            审核
          </Button>
          <Popconfirm title="确定删除这条映射？" onConfirm={() => deleteMut.mutate(record.mapping_id)}>
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
      content: `确定要删除选中的 ${selectedRowKeys.length} 条映射吗？`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => batchDeleteMut.mutate(selectedRowKeys.map(String)),
    })
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0 }}><AuditOutlined style={{ marginRight: 8 }} />Section 映射审核</h3>
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

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            value={params.review_status || 'all'} style={{ width: 130 }}
            onChange={(v) => setParams((p) => ({ ...p, review_status: v === 'all' ? undefined : v, page: 1 }))}
            options={[
              { label: '全部状态', value: 'all' },
              { label: '待审核', value: 'pending' },
              { label: '已通过', value: 'approved' },
              { label: '已拒绝', value: 'rejected' },
            ]}
          />
          <Select
            value={params.subject_id || 'all'} style={{ width: 150 }}
            onChange={(v) => setParams((p) => ({ ...p, subject_id: v === 'all' ? undefined : v, page: 1 }))}
            options={[
              { label: '全部学科', value: 'all' },
              ...subjects.map((s: any) => ({ label: s.name, value: s.id })),
            ]}
          />
        </Space>
      </Card>

      <Card>
        <Table
          dataSource={items} columns={columns} rowKey="mapping_id" loading={isLoading}
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            preserveSelectedRowKeys: true,
          }}
          pagination={{ current: params.page, total, pageSize: params.page_size, showTotal: (c) => `共 ${c} 条`, onChange: (page) => setParams((p) => ({ ...p, page })) }}
        />
      </Card>

      <Drawer
        title="审核 Section 映射" open={drawerOpen} onClose={() => setDrawerOpen(false)} width={500}
        extra={
          <Space>
            <Button danger icon={<CloseOutlined />} loading={reviewMut.isPending} onClick={() => reviewMut.mutate({ id: currentItem?.mapping_id, status: 'rejected' })}>拒绝</Button>
            <Button type="primary" icon={<CheckOutlined />} loading={reviewMut.isPending} onClick={() => reviewMut.mutate({ id: currentItem?.mapping_id, status: 'approved' })}>通过</Button>
          </Space>
        }
      >
        {currentItem && (
          <div>
            <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="原生标题">{currentItem.section_title}</Descriptions.Item>
              <Descriptions.Item label="映射章节">{currentItem.canonical_chapter_name}</Descriptions.Item>
              <Descriptions.Item label="置信度">{(currentItem.confidence * 100).toFixed(0)}%</Descriptions.Item>
              <Descriptions.Item label="映射类型">{currentItem.mapping_type}</Descriptions.Item>
              <Descriptions.Item label="当前状态">
                <Tag color={reviewStatusConfig[currentItem.review_status]?.color}>{reviewStatusConfig[currentItem.review_status]?.text}</Tag>
              </Descriptions.Item>
            </Descriptions>
            <div style={{ marginBottom: 8 }}><strong>审核备注</strong></div>
            <TextArea rows={3} value={reviewNotes} onChange={(e) => setReviewNotes(e.target.value)} placeholder="可选，填写审核意见" />
          </div>
        )}
      </Drawer>
    </div>
  )
}

export default SectionReviewPage
