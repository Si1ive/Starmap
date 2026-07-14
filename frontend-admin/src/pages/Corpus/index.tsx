import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card,
  Table,
  Button,
  Input,
  Select,
  Space,
  Tag,
  Modal,
  Form,
  message,
  Tooltip,
  Steps,
  Alert,
  Upload,
  Progress,
} from 'antd'
import {
  FolderOpenOutlined,
  SyncOutlined,
  FileTextOutlined,
  EyeOutlined,
  PlusOutlined,
  SearchOutlined,
  LoadingOutlined,
  DeleteOutlined,
  RedoOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { UploadProps } from 'antd'
import {
  listCorpusFiles,
  scanCorpusFiles,
  parseCorpusFile,
  getParseRunDetail,
  getDownloadedFiles,
  registerCorpusFileByDownload,
  deleteCorpusFile,
  batchDeleteCorpusFiles,
  uploadCorpusFiles,
} from '@/api'
import type { CorpusFile, DownloadedFile, ParseRun } from '@/types'

const { Search } = Input

const statusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'blue', text: '已注册' },
  registered: { color: 'blue', text: '已注册' },
  parsing: { color: 'processing', text: '解析中' },
  parsed: { color: 'green', text: '已解析' },
  failed: { color: 'red', text: '失败' },
}

const downloadedStatusConfig: Record<string, { color: string; text: string }> = {
  downloaded: { color: 'green', text: '已下载' },
  processing: { color: 'blue', text: '处理中' },
  processed: { color: 'purple', text: '已处理' },
  failed: { color: 'red', text: '失败' },
  skipped: { color: 'default', text: '跳过' },
}

const PIPELINE_STEPS = [
  { key: 'register', title: '注册文件' },
  { key: 'parse', title: '文档解析' },
]

const formatFileSize = (size?: number) => {
  if (!size) return '-'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

const CorpusPage = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [scanModalOpen, setScanModalOpen] = useState(false)
  const [filePickerOpen, setFilePickerOpen] = useState(false)
  const [pipelineOpen, setPipelineOpen] = useState(false)
  const [pipelineDocId, setPipelineDocId] = useState<string | null>(null)
  const [pipelineSteps, setPipelineSteps] = useState<Record<string, 'wait' | 'process' | 'finish' | 'error'>>({})
  const [parseProgress, setParseProgress] = useState<ParseRun | null>(null)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [form] = Form.useForm()

  const [params, setParams] = useState<{
    page: number
    page_size: number
    status?: string
    keyword?: string
  }>({ page: 1, page_size: 20 })
  const [fileParams, setFileParams] = useState<{
    page: number
    page_size: number
    file_type?: string
    keyword?: string
  }>({ page: 1, page_size: 10, file_type: 'pdf' })

  const { data, isLoading } = useQuery({
    queryKey: ['corpusFiles', params],
    queryFn: () => listCorpusFiles(params),
  })

  const { data: filesData, isLoading: filesLoading } = useQuery({
    queryKey: ['downloadedFiles', fileParams],
    queryFn: () => getDownloadedFiles(fileParams),
    enabled: filePickerOpen,
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

  const deleteMutation = useMutation({
    mutationFn: deleteCorpusFile,
    onSuccess: (res) => {
      message.success(`已删除：${res.data?.file_name}`)
      queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      message.error(detail || err.message || '删除失败')
    },
  })

  const batchDeleteMutation = useMutation({
    mutationFn: batchDeleteCorpusFiles,
    onSuccess: (res) => {
      message.success(`已删除 ${res.data?.deleted_count || 0} 个语料文件`)
      setSelectedRowKeys([])
      queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      message.error(detail || err.message || '删除失败')
    },
  })

  const uploadProps: UploadProps = {
    name: 'files',
    multiple: true,
    accept: '.pdf,.docx,.pptx',
    maxCount: 50,
    showUploadList: false,
    customRequest: async ({ file, onSuccess, onError }) => {
      const formData = new FormData()
      formData.append('files', file)

      try {
        const response = await uploadCorpusFiles(formData)

        if (response.data.success_count > 0) {
          message.success(`成功上传 ${response.data.success_count} 个文件`)
          queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })
        }

        if (response.data.skipped_count > 0) {
          message.info(`${response.data.skipped_count} 个文件已存在，跳过`)
        }

        if (response.data.failed_count > 0) {
          message.warning(`${response.data.failed_count} 个文件上传失败`)
        }

        onSuccess?.(response.data)
      } catch (error: any) {
        message.error(error?.response?.data?.detail || '上传失败')
        onError?.(error)
      }
    },
  }

  const files = data?.data?.items || []
  const total = data?.data?.total || 0
  const downloadedFiles = filesData?.data?.items || []
  const downloadedTotal = filesData?.data?.total || 0

  const resetPipeline = () => {
    const nextSteps: Record<string, 'wait' | 'process' | 'finish' | 'error'> = {}
    PIPELINE_STEPS.forEach((step) => {
      nextSteps[step.key] = 'wait'
    })
    setPipelineSteps(nextSteps)
    return nextSteps
  }

  // 轮询解析任务直到完成，返回 document_id；过程中更新 parseProgress
  const pollParseRun = async (runId: string): Promise<string> => {
    const MAX_ATTEMPTS = 600 // 最多轮询 20 分钟（2s 一次）
    for (let i = 0; i < MAX_ATTEMPTS; i++) {
      const res = await getParseRunDetail(runId)
      const run = res.data
      setParseProgress(run)

      if (run.status === 'success') {
        if (!run.document_id) throw new Error('解析成功但未获取到文档ID')
        return run.document_id
      }
      if (run.status === 'failed') {
        throw new Error(run.error_detail || '解析失败')
      }
      await new Promise((resolve) => setTimeout(resolve, 2000))
    }
    throw new Error('解析超时')
  }

  const runPipeline = async (fileId: string, documentId?: string) => {
    setPipelineOpen(true)
    setPipelineDocId(documentId || null)
    setParseProgress(null)
    const steps = resetPipeline()

    try {
      steps.register = 'finish'
      steps.parse = 'process'
      setPipelineSteps({ ...steps })

      // 派发解析任务，拿到 run_id 后轮询进度
      const parseRes = await parseCorpusFile(fileId, { parse_mode: 'primary' })
      const runId = parseRes.data?.run_id
      let docId = documentId
      if (runId) {
        docId = await pollParseRun(runId)
      }
      if (!docId) throw new Error('未获取到文档ID')

      steps.parse = 'finish'
      setPipelineDocId(docId)
      setParseProgress(null)
      setPipelineSteps({ ...steps })

      message.success('解析完成，请在文档详情页抽取知识点/题目')
      queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err.message
      if (typeof detail === 'string' && (detail.includes('已成功解析') || detail.includes('正在解析中'))) {
        message.info(detail)
        setPipelineOpen(false)
        queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })
        return
      }

      const currentKey = Object.keys(steps).find((key) => steps[key] === 'process')
      if (currentKey) steps[currentKey] = 'error'
      setPipelineSteps({ ...steps })
      message.error(detail || '处理失败')
    }
  }

  const handleSelectDownloadedFile = async (file: DownloadedFile) => {
    setFilePickerOpen(false)
    setPipelineOpen(true)
    const steps = resetPipeline()
    steps.register = 'process'
    setPipelineSteps({ ...steps })

    try {
      const regRes = await registerCorpusFileByDownload(file.id)
      const corpusFileId = regRes.data.corpus_file_id
      steps.register = 'finish'
      setPipelineSteps({ ...steps })
      await runPipeline(corpusFileId)
    } catch (err: any) {
      steps.register = 'error'
      setPipelineSteps({ ...steps })
      const detail = err?.response?.data?.detail
      message.error(detail || err.message || '处理失败')
    }
  }

  const handleDelete = (record: CorpusFile) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除文件 "${record.file_name}" 吗？此操作将同时删除关联的解析记录和文档数据，且无法恢复。`,
      okText: '确定',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => deleteMutation.mutate(record.id),
    })
  }

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) return
    Modal.confirm({
      title: '确认批量删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 个语料文件吗？此操作将同时删除关联的解析记录和文档数据，且无法恢复。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => batchDeleteMutation.mutate(selectedRowKeys.map(String)),
    })
  }

  const columns = [
    {
      title: '文件名',
      dataIndex: 'file_name',
      key: 'file_name',
      ellipsis: true,
      render: (text: string, record: CorpusFile) => (
        <a onClick={() => record.document_id && navigate(`/admin/corpus/${record.document_id}`)}>
          <FileTextOutlined style={{ marginRight: 8 }} />
          {text}
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
      render: formatFileSize,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const cfg = statusConfig[status] || { color: 'default', text: status }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    {
      title: '批次',
      dataIndex: 'batch_label',
      key: 'batch_label',
      width: 140,
      ellipsis: true,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (time: string) => time ? new Date(time).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_: unknown, record: CorpusFile) => (
        <Space>
          {record.document_id && (
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/admin/corpus/${record.document_id}`)}>
              详情
            </Button>
          )}
          {(record.status === 'failed' || record.status === 'pending') && (
            <Tooltip title="重新执行解析流程">
              <Button
                type="link"
                size="small"
                icon={<RedoOutlined />}
                onClick={() => runPipeline(record.id, record.document_id)}
              >
                重试
              </Button>
            </Tooltip>
          )}
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  const downloadedColumns = [
    {
      title: '文件名',
      dataIndex: 'file_name',
      ellipsis: true,
      render: (name: string, record: DownloadedFile) => (
        <Tooltip title={record.file_path || record.local_path}>
          <span>{name}</span>
        </Tooltip>
      ),
    },
    {
      title: '仓库',
      dataIndex: 'repo_name',
      width: 180,
      ellipsis: true,
    },
    {
      title: '类型',
      dataIndex: 'file_type',
      width: 70,
      render: (type: string) => <Tag>{type?.toUpperCase() || '-'}</Tag>,
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      width: 90,
      render: formatFileSize,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (status: string) => {
        const cfg = downloadedStatusConfig[status] || { color: 'default', text: status }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 110,
      render: (_: unknown, record: DownloadedFile) => (
        <Tooltip title={!record.local_path ? '文件未下载到本地，无法入库' : undefined}>
          <Button
            type="link"
            size="small"
            disabled={record.status === 'failed' || !record.local_path}
            onClick={() => handleSelectDownloadedFile(record)}
          >
            入库处理
          </Button>
        </Tooltip>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <h3 style={{ margin: 0 }}>语料管理</h3>
          <div style={{ marginTop: 4, color: 'rgba(0,0,0,0.45)' }}>
            统一管理文件注册、解析、标题树、章节映射和实体抽取。
          </div>
        </div>
        <Space>
          <Button
            danger
            icon={<DeleteOutlined />}
            disabled={selectedRowKeys.length === 0}
            loading={batchDeleteMutation.isPending}
            onClick={handleBatchDelete}
          >
            批量删除{selectedRowKeys.length ? ` (${selectedRowKeys.length})` : ''}
          </Button>
          <Button icon={<SyncOutlined />} onClick={() => queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })}>
            刷新
          </Button>
          <Upload {...uploadProps}>
            <Button icon={<UploadOutlined />}>上传文件</Button>
          </Upload>
          <Button icon={<FolderOpenOutlined />} onClick={() => setScanModalOpen(true)}>
            扫描目录
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setFileParams({ page: 1, page_size: 10, file_type: 'pdf' })
              setFilePickerOpen(true)
            }}
          >
            选择已下载文件
          </Button>
        </Space>
      </div>

      <Alert
        style={{ marginBottom: 16 }}
        type="info"
        showIcon
        message="PDF 入库已并入语料管理。新文件先注册到语料库，再按需执行解析和后续结构化处理；已解析文件不会重复处理。"
      />

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Search
            placeholder="搜索文件名"
            style={{ width: 250 }}
            onSearch={(value) => setParams((prev) => ({ ...prev, keyword: value || undefined, page: 1 }))}
            allowClear
          />
          <Select
            value={params.status || 'all'}
            style={{ width: 130 }}
            onChange={(value) => setParams((prev) => ({ ...prev, status: value === 'all' ? undefined : value, page: 1 }))}
            options={[
              { label: '全部状态', value: 'all' },
              { label: '已注册', value: 'pending' },
              { label: '解析中', value: 'parsing' },
              { label: '已解析', value: 'parsed' },
              { label: '失败', value: 'failed' },
            ]}
          />
        </Space>
      </Card>

      <Card>
        <Table
          dataSource={files}
          columns={columns}
          rowKey="id"
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            preserveSelectedRowKeys: true,
          }}
          loading={isLoading}
          scroll={{ x: 1000 }}
          pagination={{
            current: params.page,
            pageSize: params.page_size,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 个文件`,
            onChange: (page, pageSize) => setParams((prev) => ({ ...prev, page, page_size: pageSize })),
          }}
        />
      </Card>

      <Modal
        title="扫描目录注册语料"
        open={scanModalOpen}
        onCancel={() => {
          setScanModalOpen(false)
          form.resetFields()
        }}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={(values) => scanMutation.mutate({
          root_path: values.root_path,
          file_types: values.file_types ? values.file_types.split(',').map((item: string) => item.trim()).filter(Boolean) : undefined,
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
              扫描并注册
            </Button>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="选择已下载文件"
        open={filePickerOpen}
        onCancel={() => setFilePickerOpen(false)}
        footer={null}
        width={820}
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <Input
            placeholder="搜索文件名或仓库名"
            prefix={<SearchOutlined />}
            allowClear
            style={{ width: 260 }}
            value={fileParams.keyword}
            onChange={(event) => setFileParams((prev) => ({ ...prev, page: 1, keyword: event.target.value || undefined }))}
          />
          <Select
            value={fileParams.file_type || 'all'}
            style={{ width: 120 }}
            onChange={(value) => setFileParams((prev) => ({ ...prev, page: 1, file_type: value === 'all' ? undefined : value }))}
            options={[
              { label: '全部类型', value: 'all' },
              { label: 'PDF', value: 'pdf' },
              { label: 'Word', value: 'doc' },
              { label: 'PPT', value: 'ppt' },
            ]}
          />
        </Space>
        <Table
          columns={downloadedColumns}
          dataSource={downloadedFiles}
          rowKey="id"
          loading={filesLoading}
          size="small"
          pagination={{
            current: fileParams.page,
            pageSize: fileParams.page_size,
            total: downloadedTotal,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 个文件`,
            onChange: (page, pageSize) => setFileParams((prev) => ({ ...prev, page, page_size: pageSize })),
          }}
        />
      </Modal>

      <Modal
        title="入库处理进度"
        open={pipelineOpen}
        onCancel={() => setPipelineOpen(false)}
        footer={
          pipelineDocId
            ? <Button type="primary" onClick={() => navigate(`/admin/corpus/${pipelineDocId}`)}>查看文档详情</Button>
            : null
        }
        width={520}
      >
        {pipelineDocId ? <div style={{ marginBottom: 12 }}>文档ID: {pipelineDocId}</div> : null}
        <Steps
          direction="vertical"
          size="small"
          items={PIPELINE_STEPS.map((step) => {
            const status = pipelineSteps[step.key] || 'wait'
            // parse 步骤进行中时，展示解析进度详情
            let description: React.ReactNode = undefined
            if (step.key === 'parse' && status === 'process' && parseProgress) {
              description = (
                <div style={{ marginTop: 4 }}>
                  {parseProgress.total_pages && parseProgress.total_pages > 0 ? (
                    <Progress
                      percent={parseProgress.progress || 0}
                      size="small"
                      status="active"
                      format={() => `${parseProgress.current_page || 0}/${parseProgress.total_pages} 页`}
                    />
                  ) : null}
                  {parseProgress.stage_detail && (
                    <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>{parseProgress.stage_detail}</div>
                  )}
                </div>
              )
            }
            return {
              title: step.title,
              status,
              description,
              icon: status === 'process' ? <LoadingOutlined /> : undefined,
            }
          })}
        />
      </Modal>
    </div>
  )
}

export default CorpusPage
