import { useState } from 'react'
import { Card, Table, Tag, Button, Modal, Form, Input, Select, InputNumber, Row, Col, Statistic, Popconfirm, message } from 'antd'
import { PlusOutlined, HeartOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getCrawlerSources, createCrawlerSource, updateCrawlerSource, deleteCrawlerSource, checkSourceHealth } from '@/api'
import type { CrawlerSource } from '@/types'

const healthColors: Record<string, string> = {
  healthy: 'green',
  degraded: 'orange',
  unhealthy: 'red',
  unknown: 'default',
}

const CrawlerSources = () => {
  const queryClient = useQueryClient()
  const [params, setParams] = useState({ page: 1, page_size: 20 })
  const [modalVisible, setModalVisible] = useState(false)
  const [editingSource, setEditingSource] = useState<CrawlerSource | null>(null)
  const [form] = Form.useForm()

  const { data, isLoading } = useQuery({
    queryKey: ['crawlerSources', params],
    queryFn: () => getCrawlerSources(params),
  })

  const sources = (data?.data?.items || []) as CrawlerSource[]
  const total = data?.data?.total || 0

  const createMutation = useMutation({
    mutationFn: createCrawlerSource,
    onSuccess: () => {
      message.success('数据源创建成功')
      queryClient.invalidateQueries({ queryKey: ['crawlerSources'] })
      setModalVisible(false)
      form.resetFields()
    },
    onError: () => message.error('创建失败'),
  })

  const updateMutation = useMutation({
    mutationFn: (p: { id: string; data: Record<string, unknown> }) => updateCrawlerSource(p.id, p.data),
    onSuccess: () => {
      message.success('数据源更新成功')
      queryClient.invalidateQueries({ queryKey: ['crawlerSources'] })
      setModalVisible(false)
      setEditingSource(null)
      form.resetFields()
    },
    onError: () => message.error('更新失败'),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteCrawlerSource,
    onSuccess: () => {
      message.success('数据源已删除')
      queryClient.invalidateQueries({ queryKey: ['crawlerSources'] })
    },
    onError: () => message.error('删除失败'),
  })

  const healthMutation = useMutation({
    mutationFn: checkSourceHealth,
    onSuccess: (res) => {
      message.success(`健康检查完成: ${res?.data?.status || '未知'}`)
      queryClient.invalidateQueries({ queryKey: ['crawlerSources'] })
    },
    onError: () => message.error('健康检查失败'),
  })

  const handleCreate = () => {
    setEditingSource(null)
    form.resetFields()
    setModalVisible(true)
  }

  const handleEdit = (source: CrawlerSource) => {
    setEditingSource(source)
    form.setFieldsValue({
      name: source.name,
      code: source.code,
      type: source.type,
      base_url: source.base_url,
      request_interval: source.request_interval,
      daily_limit: source.daily_limit,
    })
    setModalVisible(true)
  }

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      if (editingSource) {
        updateMutation.mutate({ id: editingSource.id, data: values })
      } else {
        createMutation.mutate(values)
      }
    })
  }

  const columns = [
    { title: '名称', dataIndex: 'name', width: 150 },
    { title: '编码', dataIndex: 'code', width: 100 },
    {
      title: '类型',
      dataIndex: 'type',
      width: 100,
      render: (t: string) => {
        const map: Record<string, { text: string; color: string }> = {
          wiki: { text: '百科', color: 'blue' },
          movie: { text: '影视', color: 'green' },
          music: { text: '音乐', color: 'purple' },
          social: { text: '社交', color: 'orange' },
        }
        const c = map[t] || { text: t, color: 'default' }
        return <Tag color={c.color}>{c.text}</Tag>
      },
    },
    { title: '基础URL', dataIndex: 'base_url', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (s: string) => {
        const map: Record<string, { color: string; text: string }> = {
          active: { color: 'success', text: '启用' },
          disabled: { color: 'default', text: '禁用' },
        }
        const c = map[s] || { color: 'default', text: s }
        return <Tag color={c.color}>{c.text}</Tag>
      },
    },
    {
      title: '健康',
      dataIndex: 'health_status',
      width: 90,
      render: (h: string) => <Tag color={healthColors[h] || 'default'}>{h || '未检查'}</Tag>,
    },
    {
      title: '请求间隔',
      dataIndex: 'request_interval',
      width: 100,
      render: (v: number) => v ? `${v}s` : '-',
    },
    { title: '日限', dataIndex: 'daily_limit', width: 80 },
    { title: '总请求', dataIndex: 'total_requests', width: 80 },
    {
      title: '成功率',
      width: 80,
      render: (_: unknown, r: CrawlerSource) => {
        if (!r.total_requests) return '-'
        const rate = ((r.total_success || 0) / r.total_requests * 100).toFixed(1)
        return <span style={{ color: parseFloat(rate) >= 90 ? '#52c41a' : '#fa8c16' }}>{rate}%</span>
      },
    },
    {
      title: '平均响应',
      dataIndex: 'avg_response_time',
      width: 100,
      render: (v: number) => v ? `${v}ms` : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: CrawlerSource) => (
        <span>
          <Button type="link" size="small" icon={<HeartOutlined />} onClick={() => healthMutation.mutate(record.id)}>
            健康检查
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

  const healthyCount = sources.filter((s) => s.health_status === 'healthy').length
  const degradedCount = sources.filter((s) => s.health_status === 'degraded').length
  const unhealthyCount = sources.filter((s) => s.health_status === 'unhealthy').length

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>数据源管理</h2>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="数据源总数" value={total} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="健康" value={healthyCount} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="降级" value={degradedCount} valueStyle={{ color: '#fa8c16' }} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="不健康" value={unhealthyCount} valueStyle={{ color: '#ff4d4f' }} /></Card>
        </Col>
      </Row>

      <Card extra={<Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新增数据源</Button>}>
        <Table
          columns={columns}
          dataSource={sources as any[]}
          rowKey="id"
          loading={isLoading}
          size="small"
          scroll={{ x: 1200 }}
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

      <Modal
        title={editingSource ? '编辑数据源' : '新增数据源'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => { setModalVisible(false); setEditingSource(null); form.resetFields() }}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        width={600}
      >
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="名称" name="name" rules={[{ required: true }]}>
                <Input placeholder="如：百度百科" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="编码" name="code" rules={[{ required: true }]}>
                <Input placeholder="如：baike" disabled={!!editingSource} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="类型" name="type" rules={[{ required: true }]}>
                <Select options={[
                  { label: '百科', value: 'wiki' },
                  { label: '影视', value: 'movie' },
                  { label: '音乐', value: 'music' },
                  { label: '社交', value: 'social' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="基础URL" name="base_url" rules={[{ required: true }]}>
                <Input placeholder="https://baike.baidu.com" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item label="请求间隔(秒)" name="request_interval" initialValue={1.0}>
                <InputNumber min={0} max={60} step={0.5} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="日限" name="daily_limit" initialValue={10000}>
                <InputNumber min={100} style={{ width: '100%' }} />
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
    </div>
  )
}

export default CrawlerSources