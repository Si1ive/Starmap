import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Table, Button, Input, Select, Space, Tag, Modal, Form, message } from 'antd'
import { FolderOpenOutlined, SyncOutlined, FileTextOutlined, EyeOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listCorpusFiles, scanCorpusFiles, parseCorpusFile } from '@/api'

const { Search } = Input

const statusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'blue', text: '已注册' },
  registered: { color: 'blue', text: '已注册' },
  parsed: { color: 'green', text: '已解析' },
  parsing: { color: 'processing', text: '解析中' },
  failed: { color: 'red', text: '失败' },
}

const CorpusPage = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [params, setParams] = useState<{
    page: number
    page_size: number
    status?: string
    keyword?: string
  }>({ page: 1, page_size: 20 })
  const [scanModalOpen, setScanModalOpen] = useState(false)
  const [form] = Form.useForm()

  const { data, isLoading } = useQuery({
    queryKey: ['corpusFiles', params],
    queryFn: () => listCorpusFiles(params),
  })

  const scanMutation = useMutation({
    mutationFn: scanCorpusFiles,
    onSuccess: (res) => {
      message.success(`扫描完成：注册 ${res.data?.registered_count || 0} 个文件`)
      setScanModalOpen(false)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })
    },
  })

  const parseMutation = useMutation({
    mutationFn: parseCorpusFile,
    onSuccess: () => {
      message.success('解析任务已触发')
      queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })
    },
  })

  const files = data?.data?.items || []
  const total = data?.data?.total || 0

  const columns = [
    {
      title: '文件名',
      dataIndex: 'file_name',
      key: 'file_name',
      ellipsis: true,
      render: (text: string, record: any) => (
        <a onClick={() => record.document_id && navigate(`/admin/corpus/${record.document_id}`)}>
          <FileTextOutlined style={{ marginRight: 8 }} />{text}
        </a>
      ),
    },
    {
      title: '类型',
      dataIndex: 'file_ext',
      key: 'file_ext',
      width: 80,
      render: (ext: string) => <Tag>{ext?.toUpperCase()}</Tag>,
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (size: number) => {
        if (!size) return '-'
        if (size < 1024) return `${size} B`
        if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
        return `${(size / 1024 / 1024).toFixed(1)} MB`
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (s: string) => {
        const cfg = statusConfig[s] || { color: 'default', text: s }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    {
      title: '批次',
      dataIndex: 'batch_label',
      key: 'batch_label',
      width: 120,
      ellipsis: true,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (t: string) => t ? new Date(t).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_: any, record: any) => (
        <Space>
          {record.document_id && (
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/admin/corpus/${record.document_id}`)}>
              详情
            </Button>
          )}
          <Button type="link" size="small" icon={<PlayCircleOutlined />} onClick={() => parseMutation.mutate(record.id)}>
            解析
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0 }}>语料文件管理</h3>
        <Button type="primary" icon={<FolderOpenOutlined />} onClick={() => setScanModalOpen(true)}>
          扫描目录
        </Button>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Search
            placeholder="搜索文件名"
            style={{ width: 250 }}
            onSearch={(v) => setParams((p) => ({ ...p, keyword: v || undefined, page: 1 }))}
            allowClear
          />
          <Select
            value={params.status || 'all'}
            style={{ width: 130 }}
            onChange={(v) => setParams((p) => ({ ...p, status: v === 'all' ? undefined : v, page: 1 }))}
            options={[
              { label: '全部状态', value: 'all' },
              { label: '已注册', value: 'pending' },
              { label: '已解析', value: 'parsed' },
              { label: '解析中', value: 'parsing' },
              { label: '失败', value: 'failed' },
            ]}
          />
          <Button icon={<SyncOutlined />} onClick={() => queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })}>
            刷新
          </Button>
        </Space>
      </Card>

      <Card>
        <Table
          dataSource={files}
          columns={columns}
          rowKey="id"
          loading={isLoading}
          pagination={{
            current: params.page,
            pageSize: params.page_size,
            total,
            showTotal: (count) => `共 ${count} 个文件`,
            onChange: (page, pageSize) => setParams((p) => ({ ...p, page, page_size: pageSize })),
          }}
        />
      </Card>

      <Modal
        title="扫描目录"
        open={scanModalOpen}
        onCancel={() => setScanModalOpen(false)}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={(values) => scanMutation.mutate({
          root_path: values.root_path,
          file_types: values.file_types ? values.file_types.split(',').map((s: string) => s.trim()) : undefined,
          batch_label: values.batch_label || undefined,
        })}>
          <Form.Item name="root_path" label="根目录路径" rules={[{ required: true, message: '请输入目录路径' }]}>
            <Input placeholder="/path/to/documents" />
          </Form.Item>
          <Form.Item name="file_types" label="文件类型（逗号分隔）">
            <Input placeholder="pdf,docx,pptx" />
          </Form.Item>
          <Form.Item name="batch_label" label="批次标签">
            <Input placeholder="可选，如 2026春季" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={scanMutation.isPending} block>
              开始扫描
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default CorpusPage
