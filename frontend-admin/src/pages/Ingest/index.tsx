import { useState } from 'react'
import { Card, Table, Tag, Button, Modal, Form, Input, Select, Space, message, Progress, Tooltip } from 'antd'
import { PlusOutlined, FilePdfOutlined, ReloadOutlined, FolderOpenOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getSubjects, getChapters, ingestPdf, getIngestTasks, getDownloadedFiles } from '@/api'
import type { DownloadedFile } from '@/types'

const statusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '待执行' },
  running: { color: 'processing', text: '运行中' },
  completed: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
  stopped: { color: 'warning', text: '已停止' },
}

const fileStatusConfig: Record<string, { color: string; text: string }> = {
  downloaded: { color: 'green', text: '已下载' },
  processing: { color: 'blue', text: '处理中' },
  processed: { color: 'purple', text: '已处理' },
  failed: { color: 'red', text: '失败' },
  skipped: { color: 'default', text: '跳过' },
}

const formatFileSize = (bytes?: number) => {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const PdfIngest = () => {
  const queryClient = useQueryClient()
  const [modalVisible, setModalVisible] = useState(false)
  const [form] = Form.useForm()
  const [selectedSubject, setSelectedSubject] = useState<string | undefined>()
  const [params, setParams] = useState({ page: 1, page_size: 20 })

  // 文件选择弹窗状态
  const [filePickerVisible, setFilePickerVisible] = useState(false)
  const [fileParams, setFileParams] = useState<{
    page: number; page_size: number;
    file_type?: string; keyword?: string
  }>({ page: 1, page_size: 10, file_type: 'pdf' })

  const { data: tasksData, isLoading } = useQuery({
    queryKey: ['ingestTasks', params],
    queryFn: () => getIngestTasks(params),
  })

  const { data: subjectsData } = useQuery({
    queryKey: ['subjects'],
    queryFn: getSubjects,
  })

  const { data: chaptersData } = useQuery({
    queryKey: ['chapters', selectedSubject],
    queryFn: () => getChapters(selectedSubject!),
    enabled: !!selectedSubject,
  })

  const { data: filesData, isLoading: filesLoading } = useQuery({
    queryKey: ['downloadedFiles', fileParams],
    queryFn: () => getDownloadedFiles(fileParams),
    enabled: filePickerVisible,
  })

  const tasks = tasksData?.data?.items || []
  const total = tasksData?.data?.total || 0
  const subjects = subjectsData?.data || []
  const chapters = chaptersData?.data || []
  const downloadedFiles = (filesData?.data?.items || []) as DownloadedFile[]
  const filesTotal = filesData?.data?.total || 0

  const ingestMutation = useMutation({
    mutationFn: ingestPdf,
    onSuccess: (res) => {
      message.success(`PDF入库任务已创建: ${res.data?.task_id}`)
      setModalVisible(false)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['ingestTasks'] })
    },
  })

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      ingestMutation.mutate(values)
    })
  }

  const handleSelectFile = (file: DownloadedFile) => {
    form.setFieldValue('pdf_path', file.local_path)
    setFilePickerVisible(false)
  }

  const fileColumns = [
    {
      title: '文件名',
      dataIndex: 'file_name',
      ellipsis: true,
      render: (name: string, record: DownloadedFile) => (
        <Tooltip title={record.file_path}>
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
      title: '失败原因',
      dataIndex: 'error_detail',
      ellipsis: true,
      render: (err: string) => err ? (
        <Tooltip title={err}>
          <span style={{ color: '#ff4d4f', fontSize: 12 }}>{err}</span>
        </Tooltip>
      ) : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: DownloadedFile) => (
        <Button
          type="link"
          size="small"
          disabled={record.status === 'failed'}
          onClick={() => handleSelectFile(record)}
        >
          选择
        </Button>
      ),
    },
  ]

  const columns = [
    {
      title: '任务名称',
      dataIndex: 'name',
      width: 250,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: string) => {
        const config = statusConfig[s] || { color: 'default', text: s }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '进度',
      dataIndex: 'progress',
      width: 150,
      render: (progress: number, record: any) => (
        <Progress
          percent={Math.round(progress)}
          size="small"
          status={record.status === 'failed' ? 'exception' : record.status === 'completed' ? 'success' : 'active'}
        />
      ),
    },
    {
      title: '成功/失败',
      width: 100,
      render: (_: any, record: any) => (
        <span>
          <span style={{ color: '#52c41a' }}>{record.success_count || 0}</span>
          {' / '}
          <span style={{ color: '#ff4d4f' }}>{record.failed_count || 0}</span>
        </span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (t: string) => (t ? new Date(t).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '完成时间',
      dataIndex: 'completed_at',
      width: 180,
      render: (t: string) => (t ? new Date(t).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      ellipsis: true,
      render: (msg: string) => msg || '-',
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>PDF入库</h2>
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => queryClient.invalidateQueries({ queryKey: ['ingestTasks'] })}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setModalVisible(true)}
          >
            新增入库任务
          </Button>
        </Space>
      </div>

      <Card>
        <Table
          columns={columns}
          dataSource={tasks as any[]}
          rowKey="id"
          loading={isLoading}
          size="small"
          scroll={{ x: 1200 }}
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

      {/* 创建入库任务弹窗 */}
      <Modal
        title="新增PDF入库任务"
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => {
          setModalVisible(false)
          form.resetFields()
        }}
        confirmLoading={ingestMutation.isPending}
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="pdf_path"
            label="PDF文件路径"
            rules={[{ required: true, message: '请输入或选择PDF文件路径' }]}
            tooltip="可手动输入服务器路径，或点击右侧按钮从已下载文件中选择"
          >
            <Input
              placeholder="/data/books/王道数据结构2025.pdf"
              prefix={<FilePdfOutlined />}
              addonAfter={
                <Button
                  type="text"
                  size="small"
                  icon={<FolderOpenOutlined />}
                  onClick={() => {
                    setFileParams({ page: 1, page_size: 10, file_type: 'pdf' })
                    setFilePickerVisible(true)
                  }}
                  style={{ margin: -4, padding: '0 4px' }}
                >
                  选择文件
                </Button>
              }
            />
          </Form.Item>
          <Form.Item
            name="subject_id"
            label="学科"
            rules={[{ required: true, message: '请选择学科' }]}
          >
            <Select
              placeholder="选择学科"
              onChange={(value) => {
                setSelectedSubject(value)
                form.setFieldValue('chapter_id', undefined)
              }}
              options={subjects.map((s) => ({ label: s.name, value: s.id }))}
            />
          </Form.Item>
          <Form.Item
            name="chapter_id"
            label="章节"
            rules={[{ required: true, message: '请选择章节' }]}
          >
            <Select
              placeholder="选择章节"
              disabled={!selectedSubject}
              options={chapters.map((c) => ({ label: c.name, value: c.id }))}
            />
          </Form.Item>
          <Form.Item name="source" label="来源说明">
            <Input placeholder="如：王道2025/数据结构" />
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
    </div>
  )
}

export default PdfIngest
