import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table,
  Button,
  Tag,
  Space,
  Card,
  Progress,
  Popconfirm,
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  message,
  Statistic,
  Row,
  Col,
  Tooltip,
  Badge,
  Alert,
} from 'antd'
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  EyeOutlined,
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
  BarChartOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  MinusCircleOutlined,
  ExclamationCircleOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getCrawlerTasks, createCrawlerTask, startCrawlerTask, stopCrawlerTask, deleteCrawlerTask, getCrawlerSources, getDownloadedFiles } from '@/api'
import type { CrawlerSource, CrawlerTask, DownloadedFile } from '@/types'

// 状态配置
const statusConfig: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
  pending: { color: 'default', text: '待启动', icon: <MinusCircleOutlined /> },
  running: { color: 'processing', text: '运行中', icon: <ClockCircleOutlined /> },
  completed: { color: 'success', text: '已完成', icon: <CheckCircleOutlined /> },
  failed: { color: 'error', text: '失败', icon: <CloseCircleOutlined /> },
  stopped: { color: 'warning', text: '已停止', icon: <ExclamationCircleOutlined /> },
}

// 任务类型映射
const typeMap: Record<string, string> = {
  full: '全量爬取',
  incremental: '增量更新',
  targeted: '定向爬取',
  health_check: '健康检查',
  cleanup: '数据清理',
}

// 数据源映射
const sourceMap: Record<string, { text: string; color: string }> = {
  github: { text: 'GitHub', color: 'purple' },
  other: { text: '其他', color: 'default' },
}

// 格式化日期
const formatDate = (dateStr?: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// 格式化文件大小
const formatFileSize = (bytes?: number) => {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// 文件状态配置
const fileStatusConfig: Record<string, { color: string; text: string }> = {
  downloaded: { color: 'green', text: '已下载' },
  processing: { color: 'blue', text: '处理中' },
  processed: { color: 'purple', text: '已处理' },
  failed: { color: 'red', text: '失败' },
  skipped: { color: 'default', text: '跳过' },
}

// 格式化持续时间
const formatDuration = (start?: string, end?: string) => {
  if (!start) return '-'
  const startTime = new Date(start).getTime()
  const endTime = end ? new Date(end).getTime() : Date.now()
  const diff = Math.floor((endTime - startTime) / 1000)
  
  if (diff < 60) return `${diff}秒`
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时${Math.floor((diff % 3600) / 60)}分钟`
  return `${Math.floor(diff / 86400)}天${Math.floor((diff % 86400) / 3600)}小时`
}

const CrawlerList = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [params, setParams] = useState({ page: 1, page_size: 20 })
  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [createForm] = Form.useForm()
  const [filesModalVisible, setFilesModalVisible] = useState(false)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [filePage, setFilePage] = useState({ page: 1, page_size: 20 })

  const { data, isLoading } = useQuery({
    queryKey: ['crawlerTasks', params],
    queryFn: () => getCrawlerTasks(params),
    refetchInterval: (queryData) => {
      const items = queryData?.data?.items || []
      return items.some((task: CrawlerTask) => task.status === 'running') ? 3000 : false
    },
  })

  const { data: sourceData } = useQuery({
    queryKey: ['crawlerSources', 'taskCreate'],
    queryFn: () => getCrawlerSources({ page: 1, page_size: 100, status: 'active' }),
  })

  const tasks = data?.data?.items || []
  const total = data?.data?.total || 0
  const sources = (sourceData?.data?.items || []) as CrawlerSource[]

  const { data: filesData, isLoading: filesLoading } = useQuery({
    queryKey: ['taskFiles', selectedTaskId, filePage],
    queryFn: () => getDownloadedFiles({ task_id: selectedTaskId!, ...filePage }),
    enabled: !!selectedTaskId && filesModalVisible,
  })
  const taskFiles = (filesData?.data?.items || []) as DownloadedFile[]
  const filesTotal = filesData?.data?.total || 0

  // 统计数据
  const stats = {
    total,
    running: tasks.filter((t: CrawlerTask) => t.status === 'running').length,
    completed: tasks.filter((t: CrawlerTask) => t.status === 'completed').length,
    failed: tasks.filter((t: CrawlerTask) => t.status === 'failed').length,
    stopped: tasks.filter((t: CrawlerTask) => t.status === 'stopped').length,
    pending: tasks.filter((t: CrawlerTask) => t.status === 'pending').length,
  }

  const createMutation = useMutation({
    mutationFn: createCrawlerTask,
    onSuccess: () => {
      message.success('任务已创建并启动')
      queryClient.invalidateQueries({ queryKey: ['crawlerTasks'] })
      setCreateModalVisible(false)
      createForm.resetFields()
    },
    onError: () => undefined,
  })

  const openCreateModal = () => {
    createForm.resetFields()
    const githubSource = sources.find((s) => s.code === 'github')
    createForm.setFieldsValue({
      task_type: 'targeted',
      source_id: githubSource?.id || sources[0]?.id,
      config: {
        spider_type: 'github',
        source: 'github',
        file_types: ['pdf'],
        concurrent_limit: 3,
        delay: 1.0,
        timeout: 60,
      },
      execute_now: true,
    })
    setCreateModalVisible(true)
  }

  const startMutation = useMutation({
    mutationFn: startCrawlerTask,
    onSuccess: () => {
      message.success('任务已启动')
      queryClient.invalidateQueries({ queryKey: ['crawlerTasks'] })
    },
    onError: () => {
      message.error('启动失败')
    },
  })

  const stopMutation = useMutation({
    mutationFn: stopCrawlerTask,
    onSuccess: () => {
      message.success('任务已停止')
      queryClient.invalidateQueries({ queryKey: ['crawlerTasks'] })
    },
    onError: () => {
      message.error('停止失败')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteCrawlerTask,
    onSuccess: () => {
      message.success('任务已删除')
      queryClient.invalidateQueries({ queryKey: ['crawlerTasks'] })
    },
    onError: () => {
      message.error('删除失败')
    },
  })

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      width: 150,
      ellipsis: true,
    },
    {
      title: '任务ID',
      dataIndex: 'id',
      width: 140,
      ellipsis: true,
      render: (id: string) => (
        <Tooltip title={id}>
          <span style={{ fontFamily: 'monospace', fontSize: 13 }}>{id}</span>
        </Tooltip>
      ),
    },
    {
      title: '任务类型',
      dataIndex: 'task_type',
      width: 110,
      render: (taskType: string) => (
        <Tag color="blue" style={{ fontSize: 12 }}>
          {typeMap[taskType] || taskType}
        </Tag>
      ),
    },
    {
      title: '数据源',
      dataIndex: 'source',
      width: 100,
      render: (source: string) => {
        const config = sourceMap[source] || { text: source, color: 'default' }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '爬取统计',
      key: 'stats',
      width: 180,
      render: (_: unknown, record: CrawlerTask) => (
        <div style={{ fontSize: 13 }}>
          <div style={{ marginBottom: 4 }}>
            <span style={{ color: '#52c41a' }}>
              <CheckCircleOutlined /> {record.success_count}
            </span>
            <span style={{ margin: '0 8px', color: '#d9d9d9' }}>|</span>
            <span style={{ color: '#ff4d4f' }}>
              <CloseCircleOutlined /> {record.failed_count}
            </span>
            <span style={{ margin: '0 8px', color: '#d9d9d9' }}>|</span>
            <span style={{ color: '#1890ff' }}>
              总计 {record.completed_count}/{record.target_count}
            </span>
          </div>
          <div>
            <Badge
              color={record.success_rate >= 95 ? 'green' : record.success_rate >= 80 ? 'yellow' : 'red'}
              text={`成功率 ${record.success_rate}%`}
            />
          </div>
        </div>
      ),
    },
    {
      title: '进度',
      key: 'progress',
      width: 160,
      render: (_: unknown, record: CrawlerTask) => {
        const config = statusConfig[record.status]
        return (
          <div>
            <Progress
              percent={Math.round(record.progress)}
              size="small"
              status={
                record.status === 'failed'
                  ? 'exception'
                  : record.status === 'completed'
                  ? 'success'
                  : 'active'
              }
              format={(percent) => (
                <span style={{ fontSize: 12, fontWeight: 500 }}>{percent}%</span>
              )}
            />
            <div style={{ fontSize: 12, color: '#666', marginTop: 2 }}>
              {config.icon} {config.text}
            </div>
          </div>
        )
      },
    },
    {
      title: '时间信息',
      key: 'time',
      width: 200,
      render: (_: unknown, record: CrawlerTask) => (
        <div style={{ fontSize: 12, lineHeight: '1.8' }}>
          <div>
            <ClockCircleOutlined style={{ color: '#999', marginRight: 4 }} />
            开始: {formatDate(record.started_at)}
          </div>
          {record.completed_at && (
            <div>
              <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 4 }} />
              完成: {formatDate(record.completed_at)}
            </div>
          )}
          {record.estimated_completion && record.status === 'running' && (
            <div>
              <BarChartOutlined style={{ color: '#1890ff', marginRight: 4 }} />
              预计: {formatDate(record.estimated_completion)}
            </div>
          )}
          {record.started_at && (
            <div style={{ color: '#999' }}>
              耗时: {formatDuration(record.started_at, record.completed_at)}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      fixed: 'right' as const,
      render: (status: string) => {
        const config = statusConfig[status]
        return (
          <Tag
            color={config.color}
            icon={config.icon}
            style={{ fontSize: 12 }}
          >
            {config.text}
          </Tag>
        )
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      fixed: 'right' as const,
      render: (_: unknown, record: CrawlerTask) => (
        <Space size="small">
          {record.status === 'pending' && (
            <Button
              type="primary"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => startMutation.mutate(record.id)}
            >
              启动
            </Button>
          )}
          {record.status === 'running' && (
            <Button
              type="primary"
              danger
              size="small"
              icon={<PauseCircleOutlined />}
              onClick={() => stopMutation.mutate(record.id)}
            >
              停止
            </Button>
          )}
          {(record.status === 'failed' || record.status === 'stopped') && (
            <Button
              type="default"
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => startMutation.mutate(record.id)}
            >
              重试
            </Button>
          )}
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/admin/crawler/logs?task_id=${record.id}`)}
          >
            日志
          </Button>
          <Button
            type="text"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => {
              setSelectedTaskId(record.id)
              setFilePage({ page: 1, page_size: 20 })
              setFilesModalVisible(true)
            }}
          >
            文件
          </Button>
          <Popconfirm
            title="确认删除任务？"
            description="删除后不可恢复，是否继续？"
            onConfirm={() => deleteMutation.mutate(record.id)}
            okText="确认"
            cancelText="取消"
          >
            <Button type="text" danger size="small" icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      {/* 页面标题 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 24,
        }}
      >
        <h2 style={{ margin: 0 }}>爬虫管理</h2>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={openCreateModal}
        >
          新建任务
        </Button>
      </div>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="总任务数"
              value={stats.total}
              valueStyle={{ fontSize: 24, fontWeight: 'bold' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="运行中"
              value={stats.running}
              valueStyle={{ fontSize: 24, fontWeight: 'bold', color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="已完成"
              value={stats.completed}
              valueStyle={{ fontSize: 24, fontWeight: 'bold', color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="失败"
              value={stats.failed}
              valueStyle={{ fontSize: 24, fontWeight: 'bold', color: '#ff4d4f' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="已停止"
              value={stats.stopped}
              valueStyle={{ fontSize: 24, fontWeight: 'bold', color: '#fa8c16' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="待启动"
              value={stats.pending}
              valueStyle={{ fontSize: 24, fontWeight: 'bold', color: '#999' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 任务列表 */}
      <Card>
        <Table
          columns={columns}
          dataSource={tasks}
          rowKey="id"
          loading={isLoading}
          scroll={{ x: 1400 }}
          pagination={{
            current: params.page,
            pageSize: params.page_size,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
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

      {/* 创建任务弹窗 */}
      <Modal
        title="新建爬虫任务"
        open={createModalVisible}
        onCancel={() => {
          setCreateModalVisible(false)
          createForm.resetFields()
        }}
        onOk={() => {
          createForm.validateFields().then((values) => {
            const selectedSource = sources.find((source) => source.id === values.source_id)
            const sourceIds = values.source_id ? [values.source_id] : []
            createMutation.mutate({
              name: values.name,
              task_type: values.task_type,
              source_ids: sourceIds,
              config: {
                ...(values.config || {}),
                source: selectedSource?.code,
                source_ids: sourceIds,
              },
              execute_now: values.execute_now ?? true,
            })
          })
        }}
        confirmLoading={createMutation.isPending}
        width={600}
      >
        <Form form={createForm} layout="vertical">
          <Form.Item label="任务名称" name="name" rules={[{ required: true, message: '请输入任务名称' }]}>
            <Input placeholder="如：下载408考研数据结构PDF资料" />
          </Form.Item>
          <Form.Item label="任务类型" name="task_type" rules={[{ required: true }]} initialValue="targeted">
            <Select
              options={[
                { label: '定向爬取', value: 'targeted' },
                { label: '全量爬取', value: 'full' },
              ]}
            />
          </Form.Item>
          <Form.Item label="爬虫类型" name={['config', 'spider_type']} initialValue="github">
            <Select
              options={[
                { label: 'GitHub 仓库爬虫', value: 'github' },
              ]}
            />
          </Form.Item>
          <Form.Item label="仓库地址" name={['config', 'repo_url']}>
            <Input placeholder="https://github.com/user/repo（直接指定仓库）" />
          </Form.Item>
          <Form.Item label="搜索关键词" name={['config', 'search_query']}>
            <Input placeholder="408考研 数据结构（在 GitHub 搜索仓库）" />
          </Form.Item>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="仓库地址和搜索关键词二选一。填写仓库地址则直接爬取该仓库，填写关键词则搜索 GitHub 仓库。"
          />
          <Form.Item label="文件类型" name={['config', 'file_types']} initialValue={['pdf']}>
            <Select
              mode="multiple"
              options={[
                { label: 'PDF', value: 'pdf' },
                { label: 'Word (doc/docx)', value: 'doc' },
                { label: 'PPT (ppt/pptx)', value: 'ppt' },
              ]}
              placeholder="选择要下载的文件类型"
            />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item label="并发限制" name={['config', 'concurrent_limit']} initialValue={3}>
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="请求延迟(秒)" name={['config', 'delay']} initialValue={1.0}>
                <InputNumber min={0} max={60} step={0.5} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="超时(秒)" name={['config', 'timeout']} initialValue={60}>
                <InputNumber min={5} max={300} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="执行方式" name="execute_now" initialValue={true}>
            <Select
              options={[
                { label: '立即执行', value: true },
                { label: '仅创建', value: false },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 文件列表弹窗 */}
      <Modal
        title={`任务文件 (Task: ${selectedTaskId || ''})`}
        open={filesModalVisible}
        onCancel={() => {
          setFilesModalVisible(false)
          setSelectedTaskId(null)
        }}
        footer={null}
        width={900}
      >
        <Table
          dataSource={taskFiles}
          rowKey="id"
          loading={filesLoading}
          size="small"
          pagination={{
            current: filePage.page,
            pageSize: filePage.page_size,
            total: filesTotal,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 个文件`,
            onChange: (page, pageSize) => setFilePage({ page, page_size: pageSize }),
          }}
          columns={[
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
              width: 160,
              ellipsis: true,
            },
            {
              title: '类型',
              dataIndex: 'file_type',
              width: 60,
              render: (t: string) => <Tag>{t?.toUpperCase() || '-'}</Tag>,
            },
            {
              title: '大小',
              dataIndex: 'file_size',
              width: 80,
              render: formatFileSize,
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 70,
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
                  <span style={{ color: '#ff4d4f' }}>{err}</span>
                </Tooltip>
              ) : '-',
            },
          ]}
        />
      </Modal>
    </div>
  )
}

export default CrawlerList
