import { useState } from 'react'
import {
  Card,
  Table,
  Tag,
  Button,
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  Row,
  Col,
  Statistic,
  Popconfirm,
  message,
  Space,
  Tooltip,
  Drawer,
  Descriptions,
  Alert,
} from 'antd'
import {
  PlusOutlined,
  HeartOutlined,
  EditOutlined,
  DeleteOutlined,
  ReloadOutlined,
  EyeOutlined,
  PoweroffOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getCrawlerSources,
  createCrawlerSource,
  updateCrawlerSource,
  deleteCrawlerSource,
  checkSourceHealth,
  initializeDefaultCrawlerSources,
} from '@/api'
import type { CrawlerSource } from '@/types'

const spiderLabelMap: Record<string, string> = {
  github: 'GitHub',
}

const healthConfig: Record<string, { color: string; text: string }> = {
  healthy: { color: 'green', text: '健康' },
  degraded: { color: 'orange', text: '降级' },
  down: { color: 'red', text: '不可用' },
  unknown: { color: 'default', text: '未知' },
}

const statusConfig: Record<string, { color: string; text: string }> = {
  active: { color: 'success', text: '启用' },
  inactive: { color: 'default', text: '禁用' },
  error: { color: 'error', text: '异常' },
  deprecated: { color: 'default', text: '已废弃' },
}

const typeConfig: Record<string, { color: string; text: string }> = {
  encyclopedia: { color: 'blue', text: '百科' },
  social: { color: 'orange', text: '社交' },
  official: { color: 'green', text: '官方' },
  news: { color: 'purple', text: '新闻' },
  other: { color: 'default', text: '其他' },
}

const formatTime = (value?: string) => (value ? new Date(value).toLocaleString('zh-CN') : '-')

const CrawlerSources = () => {
  const queryClient = useQueryClient()
  const [params, setParams] = useState<{
    page: number
    page_size: number
    status?: string
    source_type?: string
  }>({ page: 1, page_size: 20 })
  const [modalVisible, setModalVisible] = useState(false)
  const [editingSource, setEditingSource] = useState<CrawlerSource | null>(null)
  const [detailSource, setDetailSource] = useState<CrawlerSource | null>(null)
  const [form] = Form.useForm()

  const { data, isLoading } = useQuery({
    queryKey: ['crawlerSources', params],
    queryFn: () => getCrawlerSources(params),
  })

  const sources = (data?.data?.items || []) as CrawlerSource[]
  const total = data?.data?.total || 0

  const invalidateSources = () => {
    queryClient.invalidateQueries({ queryKey: ['crawlerSources'] })
  }

  const createMutation = useMutation({
    mutationFn: createCrawlerSource,
    onSuccess: () => {
      message.success('数据源创建成功')
      invalidateSources()
      setModalVisible(false)
      form.resetFields()
    },
    onError: () => undefined,
  })

  const updateMutation = useMutation({
    mutationFn: (payload: { id: string; data: Record<string, unknown> }) => updateCrawlerSource(payload.id, payload.data),
    onSuccess: () => {
      message.success('数据源更新成功')
      invalidateSources()
      setModalVisible(false)
      setEditingSource(null)
      form.resetFields()
    },
    onError: () => undefined,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteCrawlerSource,
    onSuccess: () => {
      message.success('数据源已废弃')
      invalidateSources()
    },
    onError: () => undefined,
  })

  const healthMutation = useMutation({
    mutationFn: checkSourceHealth,
    onSuccess: (res) => {
      message.success(`健康检查完成: ${res?.data?.status || '未知'}`)
      invalidateSources()
    },
    onError: () => undefined,
  })

  const initMutation = useMutation({
    mutationFn: initializeDefaultCrawlerSources,
    onSuccess: (res) => {
      message.success(`默认数据源已初始化，共 ${res?.data?.total || 0} 个`)
      invalidateSources()
    },
    onError: () => undefined,
  })

  const normalizePayload = (values: Record<string, any>) => {
    let config: Record<string, any> = {}
    if (values.config_text?.trim()) {
      try {
        config = JSON.parse(values.config_text)
      } catch {
        throw new Error('配置 JSON 格式不正确')
      }
    }

    config.spider_key = values.spider_key

    return {
      name: values.name?.trim(),
      code: values.code?.trim(),
      type: values.type,
      base_url: values.base_url?.trim(),
      status: values.status || 'active',
      request_interval: values.request_interval ?? 1.0,
      daily_limit: values.daily_limit ?? 1000,
      concurrent_limit: values.concurrent_limit ?? 3,
      config,
    }
  }

  const handleCreate = () => {
    setEditingSource(null)
    form.setFieldsValue({
      type: 'code_hosting',
      status: 'active',
      request_interval: 1.0,
      daily_limit: 5000,
      concurrent_limit: 3,
      spider_key: 'github',
      config_text: '{}',
    })
    setModalVisible(true)
  }

  const handleEdit = (source: CrawlerSource) => {
    setEditingSource(source)
    form.setFieldsValue({
      name: source.name,
      code: source.code,
      type: source.type || 'other',
      base_url: source.base_url,
      status: source.status || 'active',
      request_interval: source.request_interval,
      daily_limit: source.daily_limit,
      concurrent_limit: source.concurrent_limit,
      spider_key: (source.config as any)?.spider_key || 'github',
      config_text: JSON.stringify(source.config || {}, null, 2),
    })
    setModalVisible(true)
  }

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      try {
        const payload = normalizePayload(values)
        if (editingSource) {
          updateMutation.mutate({ id: editingSource.id, data: payload })
        } else {
          createMutation.mutate(payload)
        }
      } catch (error) {
        message.error(error instanceof Error ? error.message : '数据源配置无效')
      }
    })
  }

  const toggleSourceStatus = (source: CrawlerSource) => {
    const nextStatus = source.status === 'active' ? 'inactive' : 'active'
    updateMutation.mutate({ id: source.id, data: { status: nextStatus } })
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      width: 180,
      render: (name: string, record: CrawlerSource) => (
        <div>
          <div>{name}</div>
          <Tag style={{ marginTop: 4 }}>{record.code}</Tag>
        </div>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 90,
      render: (type: string) => {
        const config = typeConfig[type] || { color: 'default', text: type || '-' }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '爬虫类型',
      width: 100,
      render: (_: unknown, record: CrawlerSource) => {
        const key = String((record.config as any)?.spider_key || '')
        const label = spiderLabelMap[key] || key || '-'
        return <Tag>{label}</Tag>
      },
    },
    {
      title: '基础URL',
      dataIndex: 'base_url',
      ellipsis: true,
      render: (url: string) => (
        <Tooltip title={url}>
          <a href={url} target="_blank" rel="noopener noreferrer">{url || '-'}</a>
        </Tooltip>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (status: string) => {
        const config = statusConfig[status] || { color: 'default', text: status || '-' }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '健康',
      dataIndex: 'health_status',
      width: 90,
      render: (health: string) => {
        const config = healthConfig[health] || healthConfig.unknown
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '限流配置',
      width: 140,
      render: (_: unknown, record: CrawlerSource) => (
        <div style={{ fontSize: 12, lineHeight: 1.8 }}>
          <div>间隔：{record.request_interval ?? '-'}s</div>
          <div>并发：{record.concurrent_limit ?? '-'}</div>
          <div>日限：{record.daily_limit ?? '-'}</div>
        </div>
      ),
    },
    {
      title: '累计统计',
      width: 140,
      render: (_: unknown, record: CrawlerSource) => {
        const rate = record.total_requests ? (((record.total_success || 0) / record.total_requests) * 100).toFixed(1) : '-'
        return (
          <div style={{ fontSize: 12, lineHeight: 1.8 }}>
            <div>请求：{record.total_requests || 0}</div>
            <div>成功：{record.total_success || 0}</div>
            <div>成功率：{rate === '-' ? '-' : `${rate}%`}</div>
          </div>
        )
      },
    },
    {
      title: '最后检查',
      dataIndex: 'last_health_check',
      width: 160,
      render: formatTime,
    },
    {
      title: '操作',
      key: 'action',
      width: 280,
      fixed: 'right' as const,
      render: (_: unknown, record: CrawlerSource) => (
        <Space size="small" wrap>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => setDetailSource(record)}>
            详情
          </Button>
          <Button type="link" size="small" icon={<HeartOutlined />} onClick={() => healthMutation.mutate(record.id)}>
            健康检查
          </Button>
          <Button type="link" size="small" icon={<PoweroffOutlined />} onClick={() => toggleSourceStatus(record)}>
            {record.status === 'active' ? '禁用' : '启用'}
          </Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确认废弃该数据源？" onConfirm={() => deleteMutation.mutate(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>废弃</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const activeCount = sources.filter((source) => source.status === 'active').length
  const healthyCount = sources.filter((source) => source.health_status === 'healthy').length
  const degradedCount = sources.filter((source) => source.health_status === 'degraded').length
  const downCount = sources.filter((source) => source.health_status === 'down').length

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>数据源管理</h2>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="数据源决定爬虫能从哪里抓取数据"
        description="任务创建时会传入数据源 ID，后端再映射到 Scrapy 支持的源编码。禁用或废弃的数据源不会出现在新任务选择中。"
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="数据源总数" value={total} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="启用中" value={activeCount} valueStyle={{ color: '#1890ff' }} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="健康/降级" value={`${healthyCount}/${degradedCount}`} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="不可用" value={downCount} valueStyle={{ color: '#ff4d4f' }} /></Card>
        </Col>
      </Row>

      <Card
        extra={(
          <Space wrap>
            <Select
              value={params.status || 'all'}
              style={{ width: 120 }}
              onChange={(value) => setParams((prev) => ({ ...prev, page: 1, status: value === 'all' ? undefined : value }))}
              options={[
                { label: '全部状态', value: 'all' },
                { label: '启用', value: 'active' },
                { label: '禁用', value: 'inactive' },
                { label: '异常', value: 'error' },
                { label: '已废弃', value: 'deprecated' },
              ]}
            />
            <Select
              value={params.source_type || 'all'}
              style={{ width: 120 }}
              onChange={(value) => setParams((prev) => ({ ...prev, page: 1, source_type: value === 'all' ? undefined : value }))}
              options={[
                { label: '全部类型', value: 'all' },
                { label: '百科', value: 'encyclopedia' },
                { label: '社交', value: 'social' },
                { label: '官方', value: 'official' },
                { label: '新闻', value: 'news' },
                { label: '其他', value: 'other' },
              ]}
            />
            <Button icon={<ReloadOutlined />} loading={initMutation.isPending} onClick={() => initMutation.mutate()}>
              初始化默认源
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新增数据源</Button>
          </Space>
        )}
      >
        <Table
          columns={columns}
          dataSource={sources as any[]}
          rowKey="id"
          loading={isLoading}
          size="small"
          scroll={{ x: 1400 }}
          pagination={{
            current: params.page,
            pageSize: params.page_size,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
          }}
          onChange={(pagination) => setParams((prev) => ({
            ...prev,
            page: pagination.current || 1,
            page_size: pagination.pageSize || 20,
          }))}
        />
      </Card>

      <Modal
        title={editingSource ? '编辑数据源' : '新增数据源'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => { setModalVisible(false); setEditingSource(null); form.resetFields() }}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        width={760}
      >
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="名称" name="name" rules={[{ required: true, message: '请输入数据源名称' }]}>
                <Input placeholder="如：百度百科" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="编码" name="code" rules={[{ required: true, message: '请输入唯一编码' }]}>
                <Input placeholder="如：baidu_baike" disabled={!!editingSource} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item label="类型" name="type" rules={[{ required: true }]}>
                <Select options={[
                  { label: '百科', value: 'encyclopedia' },
                  { label: '社交', value: 'social' },
                  { label: '官方', value: 'official' },
                  { label: '新闻', value: 'news' },
                  { label: '其他', value: 'other' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="爬虫类型" name="spider_key" rules={[{ required: true, message: '请选择爬虫类型' }]}
                tooltip="决定使用哪个爬虫来抓取该数据源">
                <Select options={[
                  { label: 'GitHub', value: 'github' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="状态" name="status" rules={[{ required: true }]}>
                <Select options={[
                  { label: '启用', value: 'active' },
                  { label: '禁用', value: 'inactive' },
                  { label: '异常', value: 'error' },
                  { label: '已废弃', value: 'deprecated' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="请求间隔(秒)" name="request_interval">
                <InputNumber min={0} max={60} step={0.5} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="基础URL" name="base_url" rules={[{ required: true, message: '请输入基础 URL' }]}>
            <Input placeholder="https://github.com" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="日请求上限" name="daily_limit">
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="并发限制" name="concurrent_limit">
                <InputNumber min={1} max={50} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="源配置(JSON)" name="config_text">
            <Input.TextArea rows={8} placeholder='{"selectors": {}, "anti_detection": {}}' />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title="数据源详情"
        open={!!detailSource}
        onClose={() => setDetailSource(null)}
        width={560}
      >
        {detailSource && (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="名称">{detailSource.name}</Descriptions.Item>
              <Descriptions.Item label="编码">{detailSource.code}</Descriptions.Item>
              <Descriptions.Item label="类型">{typeConfig[detailSource.type]?.text || detailSource.type}</Descriptions.Item>
              <Descriptions.Item label="URL">{detailSource.base_url}</Descriptions.Item>
              <Descriptions.Item label="状态">{statusConfig[detailSource.status]?.text || detailSource.status}</Descriptions.Item>
              <Descriptions.Item label="健康">{healthConfig[detailSource.health_status || 'unknown']?.text}</Descriptions.Item>
              <Descriptions.Item label="请求间隔">{detailSource.request_interval ?? '-'}s</Descriptions.Item>
              <Descriptions.Item label="并发限制">{detailSource.concurrent_limit ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="日请求上限">{detailSource.daily_limit ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="累计请求">{detailSource.total_requests || 0}</Descriptions.Item>
              <Descriptions.Item label="累计成功">{detailSource.total_success || 0}</Descriptions.Item>
              <Descriptions.Item label="累计失败">{detailSource.total_failed || 0}</Descriptions.Item>
              <Descriptions.Item label="最后健康检查">{formatTime(detailSource.last_health_check)}</Descriptions.Item>
              <Descriptions.Item label="更新时间">{formatTime(detailSource.updated_at)}</Descriptions.Item>
            </Descriptions>
            <Card size="small" title="源配置">
              <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                {JSON.stringify(detailSource.config || {}, null, 2)}
              </pre>
            </Card>
          </Space>
        )}
      </Drawer>
    </div>
  )
}

export default CrawlerSources
