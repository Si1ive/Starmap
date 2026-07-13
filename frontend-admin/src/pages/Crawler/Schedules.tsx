import { useState } from 'react'
import { Alert, Button, Card, Checkbox, Col, Form, Input, InputNumber, message, Modal, Popconfirm, Row, Select, Statistic, Table, Tag } from 'antd'
import {
  PlusOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  EditOutlined,
  DeleteOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getCrawlerSchedules,
  getCrawlerSources,
  createCrawlerSchedule,
  updateCrawlerSchedule,
  deleteCrawlerSchedule,
  toggleCrawlerSchedule,
  getScheduleRuns,
} from '@/api'
import type { CrawlerSchedule } from '@/types'
import type { CrawlerSource } from '@/types'

const CrawlerSchedules = () => {
  const queryClient = useQueryClient()
  const [params, setParams] = useState({ page: 1, page_size: 20 })
  const [modalVisible, setModalVisible] = useState(false)
  const [editingSchedule, setEditingSchedule] = useState<CrawlerSchedule | null>(null)
  const [runsModalVisible, setRunsModalVisible] = useState(false)
  const [selectedScheduleId, setSelectedScheduleId] = useState<string>('')
  const [form] = Form.useForm()
  const selectedTaskType = Form.useWatch('task_type', form) || 'targeted'
  const selectedSpiderType = Form.useWatch(['target_config', 'spider_type'], form) || 'github'
  const isCrawlTask = ['full', 'incremental', 'targeted'].includes(selectedTaskType)
  const requiresSource = isCrawlTask || selectedTaskType === 'health_check'

  const { data, isLoading } = useQuery({
    queryKey: ['crawlerSchedules', params],
    queryFn: () => getCrawlerSchedules(params),
    refetchInterval: (queryData) => {
      const items = queryData?.data?.items || []
      return items.some((schedule: CrawlerSchedule) => schedule.last_run_status === 'running') ? 5000 : false
    },
  })

  const { data: sourceData } = useQuery({
    queryKey: ['crawlerSources', 'scheduleForm'],
    queryFn: () => getCrawlerSources({ page: 1, page_size: 100, status: 'active' }),
  })

  const schedules = (data?.data?.items || []) as CrawlerSchedule[]
  const total = data?.data?.total || 0
  const sources = (sourceData?.data?.items || []) as CrawlerSource[]

  const { data: runsData, isLoading: runsLoading } = useQuery({
    queryKey: ['scheduleRuns', selectedScheduleId],
    queryFn: () => getScheduleRuns(selectedScheduleId, { page: 1, page_size: 20 }),
    enabled: !!selectedScheduleId,
    refetchInterval: runsModalVisible ? 5000 : false,
  })

  const createMutation = useMutation({
    mutationFn: createCrawlerSchedule,
    onSuccess: () => {
      message.success('定时任务创建成功')
      queryClient.invalidateQueries({ queryKey: ['crawlerSchedules'] })
      setModalVisible(false)
      form.resetFields()
    },
    onError: () => message.error('创建失败'),
  })

  const updateMutation = useMutation({
    mutationFn: (p: { id: string; data: Record<string, unknown> }) => updateCrawlerSchedule(p.id, p.data),
    onSuccess: () => {
      message.success('定时任务更新成功')
      queryClient.invalidateQueries({ queryKey: ['crawlerSchedules'] })
      setModalVisible(false)
      setEditingSchedule(null)
      form.resetFields()
    },
    onError: () => message.error('更新失败'),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteCrawlerSchedule,
    onSuccess: () => {
      message.success('定时任务已删除')
      queryClient.invalidateQueries({ queryKey: ['crawlerSchedules'] })
    },
    onError: () => message.error('删除失败'),
  })

  const toggleMutation = useMutation({
    mutationFn: (p: { id: string; enabled: boolean }) => toggleCrawlerSchedule(p.id, p.enabled),
    onSuccess: () => {
      message.success('状态已切换')
      queryClient.invalidateQueries({ queryKey: ['crawlerSchedules'] })
    },
    onError: () => message.error('切换失败'),
  })

  const handleCreate = () => {
    setEditingSchedule(null)
    form.resetFields()
    form.setFieldsValue({
      task_type: 'targeted',
      source_ids: sources[0]?.id ? [sources[0].id] : [],
      target_config: {
        spider_type: 'github',
        repo_url: '',
        search_query: '',
        pdf_path: '',
        file_types: ['pdf'],
        cleanup_types: ['duplicate', 'expired', 'orphan'],
        retention_days: 90,
        concurrent_limit: 3,
        delay: 1.0,
        timeout: 60,
      },
      cron_expression: '0 2 * * *',
      timezone: 'Asia/Shanghai',
      max_retries: 3,
      retry_interval: 300,
      concurrent_limit: 1,
      timeout: 3600,
      is_enabled: true,
    })
    setModalVisible(true)
  }

  const handleEdit = (schedule: CrawlerSchedule) => {
    const targetConfig = schedule.target_config || {}
    const configuredSpider = targetConfig.spider_type
    const spiderType = configuredSpider === 'knowledge' ? 'knowledge' : 'github'
    setEditingSchedule(schedule)
    form.setFieldsValue({
      name: schedule.name,
      description: schedule.description,
      task_type: schedule.task_type,
      source_ids: schedule.source_ids || [],
      target_config: {
        ...targetConfig,
        spider_type: spiderType,
      },
      cron_expression: schedule.cron_expression,
      timezone: schedule.timezone || 'Asia/Shanghai',
      max_retries: schedule.max_retries || 3,
      retry_interval: schedule.retry_interval || 300,
      concurrent_limit: schedule.concurrent_limit || 1,
      timeout: schedule.timeout || 3600,
    })
    setModalVisible(true)
  }

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      const taskType = values.task_type
      const crawlTask = ['full', 'incremental', 'targeted'].includes(taskType)
      const taskRequiresSource = crawlTask || taskType === 'health_check'
      const rawConfig = values.target_config || {}
      let targetConfig: Record<string, unknown> = {}
      if (crawlTask && rawConfig.spider_type === 'knowledge') {
        targetConfig = {
          spider_type: 'knowledge',
          pdf_path: rawConfig.pdf_path,
        }
      } else if (crawlTask) {
        targetConfig = {
          spider_type: 'github',
          repo_url: rawConfig.repo_url,
          search_query: rawConfig.search_query,
          file_types: rawConfig.file_types,
        }
      } else if (taskType === 'cleanup') {
        targetConfig = {
          cleanup_types: rawConfig.cleanup_types,
          retention_days: rawConfig.retention_days,
        }
      }
      const submittedValues = {
        ...values,
        source_ids: taskRequiresSource ? values.source_ids : [],
        target_config: targetConfig,
      }
      if (editingSchedule) {
        updateMutation.mutate({ id: editingSchedule.id, data: submittedValues })
      } else {
        createMutation.mutate(submittedValues)
      }
    })
  }

  const handleViewRuns = (scheduleId: string) => {
    setSelectedScheduleId(scheduleId)
    setRunsModalVisible(true)
  }

  const columns = [
    { title: '名称', dataIndex: 'name', width: 150 },
    { title: '描述', dataIndex: 'description', width: 180, ellipsis: true },
    {
      title: '任务类型',
      dataIndex: 'task_type',
      width: 100,
      render: (t: string) => {
        const map: Record<string, string> = { targeted: '定向', full: '全量', incremental: '增量', health_check: '健康检查', cleanup: '清理' }
        return <Tag color="blue">{map[t] || t}</Tag>
      },
    },
    {
      title: 'Cron 表达式',
      dataIndex: 'cron_expression',
      width: 140,
      render: (v: string) => <code style={{ background: '#f5f5f5', padding: '2px 6px', borderRadius: 4, fontSize: 13 }}>{v}</code>,
    },
    {
      title: '启用',
      dataIndex: 'is_enabled',
      width: 80,
      render: (v: boolean) => v ? <Tag color="success">启用</Tag> : <Tag color="default">禁用</Tag>,
    },
    {
      title: '执行统计',
      key: 'runs',
      width: 140,
      render: (_: unknown, r: CrawlerSchedule) => (
        <div style={{ fontSize: 12 }}>
          <span style={{ color: '#52c41a' }}>成功 {(r.success_runs || 0)}</span>
          <span style={{ margin: '0 6px', color: '#d9d9d9' }}>|</span>
          <span style={{ color: '#ff4d4f' }}>失败 {(r.failed_runs || 0)}</span>
          <span style={{ margin: '0 6px', color: '#d9d9d9' }}>|</span>
          <span>共 {(r.total_runs || 0)}</span>
        </div>
      ),
    },
    {
      title: '上次执行',
      dataIndex: 'last_run_at',
      width: 100,
      render: (v: string) => v ? new Date(v).toLocaleDateString('zh-CN') : '-',
    },
    {
      title: '上次状态',
      dataIndex: 'last_run_status',
      width: 100,
      render: (s: string) => {
        if (!s) return '-'
        const map: Record<string, { color: string; text: string }> = {
          success: { color: 'success', text: '成功' },
          failed: { color: 'error', text: '失败' },
          running: { color: 'processing', text: '运行中' },
        }
        const c = map[s] || { color: 'default', text: s }
        return <Tag color={c.color}>{c.text}</Tag>
      },
    },
    {
      title: '下次执行',
      dataIndex: 'next_run_at',
      width: 100,
      render: (v: string) => v ? new Date(v).toLocaleDateString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      render: (_: unknown, record: CrawlerSchedule) => (
        <span>
          <Button
            type="link"
            size="small"
            icon={record.is_enabled ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
            onClick={() => toggleMutation.mutate({ id: record.id, enabled: !record.is_enabled })}
          >
            {record.is_enabled ? '禁用' : '启用'}
          </Button>
          <Button type="link" size="small" icon={<HistoryOutlined />} onClick={() => handleViewRuns(record.id)}>
            历史
          </Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确认删除?" onConfirm={() => deleteMutation.mutate(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </span>
      ),
    },
  ]

  const runsColumns = [
    { title: '执行ID', dataIndex: 'id', width: 120, ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (s: string) => {
        const map: Record<string, { color: string; text: string }> = {
          success: { color: 'success', text: '成功' },
          failed: { color: 'error', text: '失败' },
          running: { color: 'processing', text: '运行中' },
        }
        const c = map[s] || { color: 'default', text: s }
        return <Tag color={c.color}>{c.text}</Tag>
      },
    },
    { title: '开始时间', dataIndex: 'started_at', width: 160 },
    { title: '完成时间', dataIndex: 'completed_at', width: 160 },
    { title: '耗时', dataIndex: 'duration', width: 80, render: (v: number) => v ? `${v}s` : '-' },
    { title: '成功/失败', key: 'counts', width: 100, render: (_: unknown, r: Record<string, any>) => (
      <span>
        <span style={{ color: '#52c41a' }}>{String(r.success_count || 0)}</span>
        <span style={{ margin: '0 4px' }}>/</span>
        <span style={{ color: '#ff4d4f' }}>{String(r.failed_count || 0)}</span>
      </span>
    )},
    { title: '错误信息', dataIndex: 'error_message', ellipsis: true },
  ]

  const enabledCount = schedules.filter((s) => s.is_enabled).length

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>定时任务</h2>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={8}>
          <Card size="small"><Statistic title="总任务数" value={total} /></Card>
        </Col>
        <Col xs={8}>
          <Card size="small"><Statistic title="已启用" value={enabledCount} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col xs={8}>
          <Card size="small"><Statistic title="已禁用" value={total - enabledCount} valueStyle={{ color: '#999' }} /></Card>
        </Col>
      </Row>

      <Card extra={<Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新建定时任务</Button>}>
        <Table
          columns={columns}
          dataSource={schedules as any[]}
          rowKey="id"
          loading={isLoading}
          size="small"
          scroll={{ x: 1400 }}
          pagination={{
            current: params.page,
            pageSize: params.page_size,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
          }}
          onChange={(pagination) => setParams({ page: pagination.current || 1, page_size: pagination.pageSize || 20 })}
        />
      </Card>

      {/* 创建/编辑弹窗 */}
      <Modal
        title={editingSchedule ? '编辑定时任务' : '新建定时任务'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => { setModalVisible(false); setEditingSchedule(null); form.resetFields() }}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item label="名称" name="name" rules={[{ required: true }]}>
            <Input placeholder="如：每日增量爬取" />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={2} placeholder="定时任务描述" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item label="任务类型" name="task_type" rules={[{ required: true }]} initialValue="targeted">
                <Select options={[
                  { label: '定向爬取', value: 'targeted' },
                  { label: '全量爬取', value: 'full' },
                  { label: '增量更新', value: 'incremental' },
                  { label: '健康检查', value: 'health_check' },
                  { label: '数据清理', value: 'cleanup' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="Cron表达式" name="cron_expression" rules={[{ required: true }]} initialValue="0 2 * * *">
                <Input placeholder="0 2 * * *" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="时区" name="timezone" initialValue="Asia/Shanghai">
                <Select options={[
                  { label: 'Asia/Shanghai', value: 'Asia/Shanghai' },
                  { label: 'UTC', value: 'UTC' },
                ]} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            {requiresSource && (
              <Col span={12}>
                <Form.Item
                  label="数据源"
                  name="source_ids"
                  preserve={false}
                  rules={[{ required: true, message: '请选择数据源' }]}
                >
                  <Select
                    mode="multiple"
                    options={sources.map((source) => ({
                      label: source.name,
                      value: source.id,
                    }))}
                  />
                </Form.Item>
              </Col>
            )}
            {isCrawlTask && (
              <Col span={12}>
                <Form.Item
                  label="爬虫类型"
                  name={['target_config', 'spider_type']}
                  initialValue="github"
                  preserve={false}
                  rules={[{ required: true, message: '请选择爬虫类型' }]}
                >
                  <Select options={[
                    { label: 'GitHub 仓库爬虫', value: 'github' },
                    { label: 'PDF 知识抽取', value: 'knowledge' },
                  ]} />
                </Form.Item>
              </Col>
            )}
          </Row>
          {isCrawlTask && selectedSpiderType === 'github' && (
            <>
              <Form.Item
                label="仓库地址"
                name={['target_config', 'repo_url']}
                preserve={false}
                dependencies={[['target_config', 'search_query']]}
                rules={[
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (value || getFieldValue(['target_config', 'search_query'])) {
                        return Promise.resolve()
                      }
                      return Promise.reject(new Error('仓库地址和搜索关键词至少填写一项'))
                    },
                  }),
                ]}
              >
                <Input placeholder="https://github.com/user/repo" />
              </Form.Item>
              <Form.Item
                label="搜索关键词"
                name={['target_config', 'search_query']}
                preserve={false}
              >
                <Input placeholder="408考研 数据结构" />
              </Form.Item>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
                message="仓库地址和搜索关键词二选一。"
              />
              <Form.Item
                label="文件类型"
                name={['target_config', 'file_types']}
                initialValue={['pdf']}
                preserve={false}
              >
                <Select
                  mode="multiple"
                  options={[
                    { label: 'PDF', value: 'pdf' },
                    { label: 'Word (doc/docx)', value: 'doc' },
                    { label: 'PPT (ppt/pptx)', value: 'ppt' },
                  ]}
                />
              </Form.Item>
            </>
          )}
          {isCrawlTask && selectedSpiderType === 'knowledge' && (
            <Form.Item
              label="PDF 路径"
              name={['target_config', 'pdf_path']}
              preserve={false}
              rules={[{ required: true, message: '请输入后端可访问的 PDF 路径' }]}
            >
              <Input placeholder="/data/corpus/example.pdf" />
            </Form.Item>
          )}
          {selectedTaskType === 'cleanup' && (
            <Row gutter={16}>
              <Col span={16}>
                <Form.Item
                  label="清理范围"
                  name={['target_config', 'cleanup_types']}
                  initialValue={['duplicate', 'expired', 'orphan']}
                  preserve={false}
                  rules={[{ required: true, message: '至少选择一种清理类型' }]}
                >
                  <Checkbox.Group
                    options={[
                      { label: '重复下载记录', value: 'duplicate' },
                      { label: '过期日志/失败文件', value: 'expired' },
                      { label: '孤立任务引用', value: 'orphan' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  label="保留天数"
                  name={['target_config', 'retention_days']}
                  initialValue={90}
                  preserve={false}
                  rules={[{ required: true, message: '请输入保留天数' }]}
                >
                  <InputNumber min={1} max={3650} precision={0} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
          )}
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item label="最大重试" name="max_retries" initialValue={3}>
                <InputNumber min={0} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="重试间隔(秒)" name="retry_interval" initialValue={300}>
                <InputNumber min={60} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="并发限制" name="concurrent_limit" initialValue={3}>
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 执行历史弹窗 */}
      <Modal
        title="执行历史"
        open={runsModalVisible}
        onCancel={() => setRunsModalVisible(false)}
        footer={null}
        width={900}
      >
        <Table
          columns={runsColumns}
          dataSource={(runsData?.data?.items || []) as any[]}
          rowKey="id"
          loading={runsLoading}
          size="small"
          pagination={{ pageSize: 10 }}
        />
      </Modal>
    </div>
  )
}

export default CrawlerSchedules
