import { useState } from 'react'
import { Card, Table, Button, Select, Space, Tag, Input, message, Descriptions, Drawer, Modal, Popconfirm } from 'antd'
import { CheckOutlined, CloseOutlined, BranchesOutlined, DeleteOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listRelationReviews, reviewRelation, deleteReviewRelation, batchDeleteReviewRelations } from '@/api'

const { TextArea } = Input

const reviewStatusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'orange', text: '待审核' }, approved: { color: 'green', text: '已通过' }, rejected: { color: 'red', text: '已拒绝' },
}
const relationTypeConfig: Record<string, { color: string; text: string }> = {
  prerequisite: { color: 'blue', text: '先修关系' },
  similar_to: { color: 'cyan', text: '相似' },
  contrast_with: { color: 'volcano', text: '对比' },
  common_confusion: { color: 'magenta', text: '易混淆' },
  contains: { color: 'green', text: '包含' },
  part_of: { color: 'lime', text: '属于' },
  used_in: { color: 'geekblue', text: '应用于' },
}

const RelationReviewPage = () => {
  const queryClient = useQueryClient()
  const [params, setParams] = useState<{ page: number; page_size: number; review_status?: string; relation_type?: string }>({
    page: 1, page_size: 20, review_status: 'pending',
  })
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [currentItem, setCurrentItem] = useState<any>(null)
  const [reviewNotes, setReviewNotes] = useState('')
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const { data, isLoading } = useQuery({ queryKey: ['relationReviews', params], queryFn: () => listRelationReviews(params) })

  const reviewMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      reviewRelation(id, { review_status: status, review_notes: reviewNotes || undefined }),
    onSuccess: () => {
      message.success('操作成功')
      setDrawerOpen(false); setCurrentItem(null); setReviewNotes('')
      queryClient.invalidateQueries({ queryKey: ['relationReviews'] })
    },
  })

  const changeTypeMut = useMutation({
    mutationFn: ({ id, newType }: { id: string; newType: string }) =>
      reviewRelation(id, { review_status: 'pending', relation_type: newType }),
    onSuccess: () => {
      message.success('关系类型已修改，状态重置为待审核')
      setDrawerOpen(false); setCurrentItem(null)
      queryClient.invalidateQueries({ queryKey: ['relationReviews'] })
    },
  })

  const deleteMut = useMutation({
    mutationFn: deleteReviewRelation,
    onSuccess: (_, id) => {
      message.success('删除成功')
      if (currentItem?.relation_id === id) {
        setDrawerOpen(false)
        setCurrentItem(null)
        setReviewNotes('')
      }
      queryClient.invalidateQueries({ queryKey: ['relationReviews'] })
    },
  })

  const batchDeleteMut = useMutation({
    mutationFn: batchDeleteReviewRelations,
    onSuccess: (res) => {
      message.success(`已删除 ${res.data?.deleted_count || 0} 条关系`)
      setSelectedRowKeys([])
      if (currentItem && selectedRowKeys.includes(currentItem.relation_id)) {
        setDrawerOpen(false)
        setCurrentItem(null)
        setReviewNotes('')
      }
      queryClient.invalidateQueries({ queryKey: ['relationReviews'] })
    },
  })

  const items = data?.data?.items || []
  const total = data?.data?.total || 0

  const columns = [
    { title: '源知识点', dataIndex: 'source_title', key: 'source_title', ellipsis: true, render: (t: string) => <strong>{t}</strong> },
    { title: '', key: 'arrow', width: 80, render: (_: any, record: any) => {
      const cfg = relationTypeConfig[record.relation_type] || { color: 'default', text: record.relation_type }
      return <Tag color={cfg.color} style={{ fontSize: 11 }}>{cfg.text}</Tag>
    }},
    { title: '目标知识点', dataIndex: 'target_title', key: 'target_title', ellipsis: true, render: (t: string) => <strong>{t}</strong> },
    { title: '证据', dataIndex: 'evidence_text', key: 'evidence_text', ellipsis: true, render: (t: string) => t?.slice(0, 60) || '-' },
    { title: '状态', dataIndex: 'review_status', key: 'review_status', width: 100, render: (s: string) => <Tag color={reviewStatusConfig[s]?.color}>{reviewStatusConfig[s]?.text || s}</Tag> },
    { title: '操作', key: 'actions', width: 120, render: (_: any, record: any) => (
      <Space size="small">
        <Button type="link" size="small" onClick={() => { setCurrentItem(record); setReviewNotes(record.review_notes || ''); setDrawerOpen(true) }}>审核</Button>
        <Popconfirm title="确定删除这条关系？" onConfirm={() => deleteMut.mutate(record.relation_id)}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      </Space>
    )},
  ]

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) return
    Modal.confirm({
      title: '确认批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 条关系吗？`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => batchDeleteMut.mutate(selectedRowKeys.map(String)),
    })
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0 }}><BranchesOutlined style={{ marginRight: 8 }} />关系审核</h3>
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
          <Select value={params.review_status || 'all'} style={{ width: 130 }}
            onChange={(v) => setParams((p) => ({ ...p, review_status: v === 'all' ? undefined : v, page: 1 }))}
            options={[{ label: '全部状态', value: 'all' }, { label: '待审核', value: 'pending' }, { label: '已通过', value: 'approved' }, { label: '已拒绝', value: 'rejected' }]}
          />
          <Select value={params.relation_type || 'all'} style={{ width: 150 }}
            onChange={(v) => setParams((p) => ({ ...p, relation_type: v === 'all' ? undefined : v, page: 1 }))}
            options={[{ label: '全部类型', value: 'all' }, ...Object.entries(relationTypeConfig).map(([k, v]) => ({ label: v.text, value: k }))]}
          />
        </Space>
      </Card>
      <Card>
        <Table dataSource={items} columns={columns} rowKey="relation_id" loading={isLoading}
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            preserveSelectedRowKeys: true,
          }}
          pagination={{ current: params.page, total, pageSize: params.page_size, showTotal: (c) => `共 ${c} 条`, onChange: (page) => setParams((p) => ({ ...p, page })) }}
        />
      </Card>
      <Drawer title="审核关系" open={drawerOpen} onClose={() => setDrawerOpen(false)} width={550}
        extra={<Space>
          <Button danger icon={<CloseOutlined />} loading={reviewMut.isPending} onClick={() => reviewMut.mutate({ id: currentItem?.relation_id, status: 'rejected' })}>拒绝</Button>
          <Button type="primary" icon={<CheckOutlined />} loading={reviewMut.isPending} onClick={() => reviewMut.mutate({ id: currentItem?.relation_id, status: 'approved' })}>通过</Button>
        </Space>}
      >
        {currentItem && (
          <div>
            <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="源知识点">{currentItem.source_title}</Descriptions.Item>
              <Descriptions.Item label="目标知识点">{currentItem.target_title}</Descriptions.Item>
              <Descriptions.Item label="关系类型">
                <Tag color={relationTypeConfig[currentItem.relation_type]?.color}>{relationTypeConfig[currentItem.relation_type]?.text || currentItem.relation_type}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="证据"><div style={{ maxHeight: 100, overflow: 'auto' }}>{currentItem.evidence_text || '-'}</div></Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={reviewStatusConfig[currentItem.review_status]?.color}>{reviewStatusConfig[currentItem.review_status]?.text}</Tag></Descriptions.Item>
            </Descriptions>
            <div style={{ marginBottom: 16 }}>
              <strong style={{ display: 'block', marginBottom: 8 }}>修改关系类型</strong>
              <Select value={currentItem.relation_type} style={{ width: '100%' }}
                onChange={(newType) => changeTypeMut.mutate({ id: currentItem.relation_id, newType })}
                options={Object.entries(relationTypeConfig).map(([k, v]) => ({ label: v.text, value: k }))}
              />
            </div>
            <div style={{ marginBottom: 8 }}><strong>审核备注</strong></div>
            <TextArea rows={3} value={reviewNotes} onChange={(e) => setReviewNotes(e.target.value)} placeholder="可选" />
          </div>
        )}
      </Drawer>
    </div>
  )
}

export default RelationReviewPage
