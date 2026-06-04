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
  message,
  Statistic,
  Row,
  Col,
  Tooltip,
  Badge,
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
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getCrawlerTasks, createCrawlerTask, stopCrawlerTask } from '@/api'
import type { CrawlerTask } from '@/types'

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
}

// 数据源映射
const sourceMap: Record<string, { text: string; color: string }> = {
  wikipedia: { text: '维基百科', color: 'blue' },
  douban: { text: '豆瓣', color: 'green' },
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

  const { data, isLoading } = useQuery({
    queryKey: ['crawlerTasks', params],
    queryFn: () => getCrawlerTasks(params),
  })

  const tasks = data?.data?.items || []

  // 统计数据
  const stats = {
    total: tasks.length,
    running: tasks.filter((t: CrawlerTask) => t.status === 'running').length,
    completed: tasks.filter((t: CrawlerTask) => t.status === 'completed').length,
    failed: tasks.filter((t: CrawlerTask) => t.status === 'failed').length,
    stopped: tasks.filter((t: CrawlerTask) => t.status === 'stopped').length,
    pending: tasks.filter((t: CrawlerTask) => t.status === 'pending').length,
  }

  const startMutation = useMutation({
    mutationFn: createCrawlerTask,
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

  const columns = [
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
      dataIndex: 'type',
      width: 110,
      render: (type: string) => (
        <Tag color="blue" style={{ fontSize: 12 }}>
          {typeMap[type] || type}
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
              <CloseCircleOutlined /> {record.fail_count}
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
              onClick={() => startMutation.mutate({ id: record.id })}
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
              onClick={() => startMutation.mutate({ id: record.id })}
            >
              重试
            </Button>
          )}
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/admin/crawler/${record.id}`)}
          >
            日志
          </Button>
          <Popconfirm
            title="确认删除任务？"
            description="删除后不可恢复，是否继续？"
            onConfirm={() => message.info('删除功能开发中')}
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
          onClick={() => message.info('新建任务功能开发中')}
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
          scroll={{ x: 1200 }}
          pagination={{
            current: params.page,
            pageSize: params.page_size,
            total: data?.data?.total || 0,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
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
    </div>
  )
}

export default CrawlerList
