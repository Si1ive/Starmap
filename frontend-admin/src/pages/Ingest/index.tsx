import { useState } from 'react'
import { Card, Table, Tag, Button, Modal, Form, Input, Select, Space, message, Steps, Tooltip } from 'antd'
import { PlusOutlined, FilePdfOutlined, ReloadOutlined, FolderOpenOutlined, SearchOutlined, LoadingOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listCorpusFiles, scanCorpusFiles, parseCorpusFile, extractDocumentSections, mapDocumentChapters, getDownloadedFiles, registerCorpusFileByDownload } from '@/api'

const { Search } = Input

const statusConfig: Record<string, { color: string; text: string }> = {
  registered: { color: 'blue', text: '已注册' },
  parsed: { color: 'green', text: '已解析' },
  parsing: { color: 'processing', text: '解析中' },
  failed: { color: 'red', text: '失败' },
}

const fileStatusConfig: Record<string, { color: string; text: string }> = {
  downloaded: { color: 'green', text: '已下载' },
  processing: { color: 'blue', text: '处理中' },
  processed: { color: 'purple', text: '已处理' },
  failed: { color: 'red', text: '失败' },
  skipped: { color: 'default', text: '跳过' },
}

// 处理步骤
const PIPELINE_STEPS = [
  { key: 'scan', title: '扫描注册' },
  { key: 'parse', title: '文档解析' },
  { key: 'sections', title: '提取标题树' },
  { key: 'map', title: '映射章节' },
]

const PdfIngest = () => {
  const queryClient = useQueryClient()
  const [modalVisible, setModalVisible] = useState(false)
  const [form] = Form.useForm()
  const [params, setParams] = useState({ page: 1, page_size: 20, status: undefined as string | undefined })
  const [keyword, setKeyword] = useState<string | undefined>()

  // 文件选择弹窗
  const [filePickerVisible, setFilePickerVisible] = useState(false)
  const [fileParams, setFileParams] = useState<{
    page: number; page_size: number; file_type?: string; keyword?: string
  }>({ page: 1, page_size: 10, file_type: 'pdf' })

  // 管线进度弹窗
  const [pipelineVisible, setPipelineVisible] = useState(false)
  const [pipelineSteps, setPipelineSteps] = useState<Record<string, 'wait' | 'process' | 'finish' | 'error'>>({})
  const [pipelineDocId, setPipelineDocId] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['corpusFiles', params, keyword],
    queryFn: () => listCorpusFiles({ ...params, keyword }),
  })

  const { data: filesData, isLoading: filesLoading } = useQuery({
    queryKey: ['downloadedFiles', fileParams],
    queryFn: () => getDownloadedFiles(fileParams),
    enabled: filePickerVisible,
  })

  const files = data?.data?.items || []
  const total = data?.data?.total || 0
  const downloadedFiles = (filesData?.data?.items || []) as any[]
  const filesTotal = filesData?.data?.total || 0

  // 扫描并自动走完全流程
  const scanMutation = useMutation({
    mutationFn: scanCorpusFiles,
    onSuccess: async (res) => {
      const count = res.data?.registered_count || 0
      message.success(`扫描完成：注册 ${count} 个文件`)
      setModalVisible(false)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })

      // 如果有注册成功的文件，提示用户可批量处理
      if (count > 0) {
        message.info('可在列表中点击"自动处理"逐个处理文件，或等待后续批量处理功能')
      }
    },
  })

  // 自动处理管线：解析 → 提取标题 → 映射章节
  const runPipeline = async (fileId: string, documentId?: string) => {
    setPipelineVisible(true)
    setPipelineDocId(documentId || null)
    const steps: Record<string, 'wait' | 'process' | 'finish' | 'error'> = {}
    PIPELINE_STEPS.forEach((s) => (steps[s.key] = 'wait'))
    setPipelineSteps({ ...steps })

    try {
      // Step 1: 解析（如果还没解析）
      steps.scan = 'finish'
      steps.parse = 'process'
      setPipelineSteps({ ...steps })

      const parseRes = await parseCorpusFile(fileId, {
        parse_mode: 'primary',
      })
      if (parseRes.code !== 0) throw new Error(parseRes.message || '解析失败')

      steps.parse = 'finish'
      steps.sections = 'process'
      setPipelineSteps({ ...steps })

      // 从解析结果获取 document_id
      const docId = parseRes.data?.document_id || documentId
      if (!docId) throw new Error('未获取到文档ID')

      setPipelineDocId(docId)

      // Step 2: 提取标题树
      const sectionsRes = await extractDocumentSections(docId)
      if (sectionsRes.code !== 0) throw new Error(sectionsRes.message || '提取标题树失败')

      steps.sections = 'finish'

      // Step 3: 映射章节（不选学科则遍历所有学科自动匹配）
      steps.map = 'process'
      setPipelineSteps({ ...steps })

      const subjectId = form.getFieldValue('subject_id')
      const mapRes = await mapDocumentChapters(docId, subjectId || undefined)
      if (mapRes.code !== 0) {
        steps.map = 'error'
        setPipelineSteps({ ...steps })
        message.warning('章节映射部分失败，可在详情页手动处理')
      } else {
        steps.map = 'finish'
        setPipelineSteps({ ...steps })
      }

      queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })
      message.success('自动处理完成')
    } catch (err: any) {
      // 标记当前步骤为错误
      const currentKey = Object.keys(steps).find((k) => steps[k] === 'process')
      if (currentKey) steps[currentKey] = 'error'
      setPipelineSteps({ ...steps })
      message.error(err.message || '处理失败')
    }
  }

  const handleSelectFile = async (file: any) => {
    setFilePickerVisible(false)
    try {
      const regRes = await registerCorpusFileByDownload(file.id)
      if (regRes.code !== 0) {
        message.error(regRes.message || '注册失败')
        return
      }
      const corpusFileId = regRes.data!.corpus_file_id
      await runPipeline(corpusFileId)
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      message.error(detail || err.message || '处理失败')
    }
  }

  const handleCreateAndProcess = () => {
    form.validateFields().then((values) => {
      scanMutation.mutate({
        root_path: values.root_path,
        batch_label: values.batch_label || undefined,
      })
    })
  }

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return '-'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const fileColumns = [
    {
      title: '文件名',
      dataIndex: 'file_name',
      ellipsis: true,
      render: (name: string, record: any) => (
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
      render: (t: string) => <Tag>{t?.toUpperCase() || '-'}</Tag>,
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
      width: 80,
      render: (s: string) => {
        const config = fileStatusConfig[s] || { color: 'default', text: s }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, record: any) => (
        <Tooltip title={!record.local_path ? '文件未下载到本地，无法处理' : undefined}>
          <Button
            type="link"
            size="small"
            disabled={record.status === 'failed' || !record.local_path}
            onClick={() => handleSelectFile(record)}
          >
            选择并处理
          </Button>
        </Tooltip>
      ),
    },
  ]

  const columns = [
    {
      title: '文件名',
      dataIndex: 'file_name',
      key: 'file_name',
      ellipsis: true,
      render: (text: string) => (
        <span>
          <FilePdfOutlined style={{ marginRight: 8 }} />
          {text}
        </span>
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
      width: 170,
      render: (t: string) => t ? new Date(t).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: any, record: any) => (
        <Space>
          <Button
            type="primary"
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={() => runPipeline(record.id, record.document_id)}
          >
            自动处理
          </Button>
          {record.document_id && (
            <Button
              type="link"
              size="small"
              onClick={() => window.open(`/admin/corpus/${record.document_id}`, '_blank')}
            >
              详情
            </Button>
          )}
        </Space>
      ),
    },
  ]

  const stepStatusToAntd = (s: 'wait' | 'process' | 'finish' | 'error') => s

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>PDF 入库</h2>
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => queryClient.invalidateQueries({ queryKey: ['corpusFiles'] })}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setFileParams({ page: 1, page_size: 10, file_type: 'pdf' })
              setFilePickerVisible(true)
            }}
          >
            选择文件入库
          </Button>
          <Button
            icon={<FolderOpenOutlined />}
            onClick={() => setModalVisible(true)}
          >
            扫描目录
          </Button>
        </Space>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Search
            placeholder="搜索文件名"
            style={{ width: 250 }}
            onSearch={(v) => setKeyword(v || undefined)}
            allowClear
          />
          <Select
            value={params.status || 'all'}
            style={{ width: 130 }}
            onChange={(v) => setParams((p) => ({ ...p, status: v === 'all' ? undefined : v, page: 1 }))}
            options={[
              { label: '全部状态', value: 'all' },
              { label: '已注册', value: 'registered' },
              { label: '已解析', value: 'parsed' },
              { label: '解析中', value: 'parsing' },
              { label: '失败', value: 'failed' },
            ]}
          />
        </Space>
      </Card>

      <Card>
        <Table
          columns={columns}
          dataSource={files}
          rowKey="id"
          loading={isLoading}
          size="small"
          scroll={{ x: 1000 }}
          pagination={{
            current: params.page,
            pageSize: params.page_size,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 个文件`,
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

      {/* 扫描目录弹窗（批量操作） */}
      <Modal
        title="扫描目录入库"
        open={modalVisible}
        onCancel={() => { setModalVisible(false); form.resetFields() }}
        footer={null}
        width={500}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="root_path"
            label="扫描目录"
            rules={[{ required: true, message: '请输入目录路径' }]}
            tooltip="填写文件所在目录，系统会自动扫描并注册所有支持的文件（pdf/docx/pptx）"
          >
            <Input placeholder="/data/books/" />
          </Form.Item>

          <Form.Item name="batch_label" label="批次标签">
            <Input placeholder="可选，如 2026春季" />
          </Form.Item>

          <Form.Item>
            <Button
              type="primary"
              icon={<FolderOpenOutlined />}
              loading={scanMutation.isPending}
              block
              onClick={handleCreateAndProcess}
            >
              扫描并注册
            </Button>
          </Form.Item>
        </Form>
      </Modal>

      {/* 文件选择弹窗 */}
      <Modal
        title="选择已下载文件"
        open={filePickerVisible}
        onCancel={() => setFilePickerVisible(false)}
        footer={null}
        width={800}
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <Input
            placeholder="搜索文件名或仓库名"
            prefix={<SearchOutlined />}
            allowClear
            style={{ width: 250 }}
            value={fileParams.keyword}
            onChange={(e) => setFileParams((prev) => ({ ...prev, page: 1, keyword: e.target.value || undefined }))}
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
          columns={fileColumns}
          dataSource={downloadedFiles}
          rowKey="id"
          loading={filesLoading}
          size="small"
          pagination={{
            current: fileParams.page,
            pageSize: fileParams.page_size,
            total: filesTotal,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 个文件`,
          }}
          onChange={(pagination) =>
            setFileParams((prev) => ({
              ...prev,
              page: pagination.current || 1,
              page_size: pagination.pageSize || 10,
            }))
          }
        />
      </Modal>

      {/* 自动处理进度弹窗 */}
      <Modal
        title="自动处理进度"
        open={pipelineVisible}
        onCancel={() => setPipelineVisible(false)}
        footer={
          pipelineDocId
            ? <Button type="primary" href={`/admin/corpus/${pipelineDocId}`} target="_blank">查看文档详情</Button>
            : null
        }
        width={500}
      >
        <Steps
          direction="vertical"
          size="small"
          items={PIPELINE_STEPS.map((step) => {
            const s = pipelineSteps[step.key] || 'wait'
            return {
              title: step.title,
              status: stepStatusToAntd(s),
              icon: s === 'process' ? <LoadingOutlined /> : undefined,
            }
          })}
        />
      </Modal>
    </div>
  )
}

export default PdfIngest
