import { useState } from 'react'
import { Table, Button, Tag, Space, Card, Progress, Popconfirm, message } from 'antd'
import { PlayCircleOutlined, PauseCircleOutlined, EyeOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getCrawlerTasks, createCrawlerTask, stopCrawlerTask } from '@/api'
import type { CrawlerTask } from '@/types'

const statusMap: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '待启动' },
  running: { color: 'processing', text: '运行中' },
  completed: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
  stopped: { color: 'warning', text: '已停止' },
}

const CrawlerList = () => {
  const queryClient = useQueryClient()
  const [params, setParams] = useState({ page: 1, page_size: 20 })

  const { data, isLoading } = useQuery({
    queryKey: ['crawlerTasks', params],
    queryFn: () => getCrawlerTasks(params),
  })

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
      width: 150,
      ellipsis: true,
    },
    {
      title: '任务类型',
      dataIndex: 'type',
      render: (type: string) => {
        const typeMap: Record<string, string> = {
          full: '全量爬取',
          incremental: '增量更新',
          targeted: '定向爬取',
        }
        return typeMap[type] || type
      },
    },
    {
      title: '数据源',
      dataIndex: 'source',
    },
    {
      title: '进度',
      key: 'progress',
      render: (_: unknown, record: CrawlerTask) => (
        <div style={{ width: 200 }}>
          <Progress
            percent={Math.round(record.progress)}
            size="small"
            status={record.status === 'failed' ? 'exception' : record.status === 'completed' ? 'success' : 'active'}
          />
          <div style={{ fontSize: 12, color: '#666' }}>
            {record.completed_count} / {record.target_count}
          </div>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (status: string) => {
        const config = statusMap[status] || { color: 'default', text: status }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '开始时间',
      dataIndex: 'started_at',
    },
    {
      title: '操作',
      key: 'action',
      width: 250,
      render: (_: unknown, record: CrawlerTask) => (
        <Space>
          {record.status === 'pending' && (
            <Button
              type="text"
              icon={<PlayCircleOutlined />}
              onClick={() => startMutation.mutate({ id: record.id })}
            >
              启动
            </Button>
          )}
          {record.status === 'running' && (
            <Button
              type="text"
              icon={<PauseCircleOutlined />}
              onClick={() => stopMutation.mutate(record.id)}
            >
              停止
            </Button>
          )}
          <Button type="text" icon={<EyeOutlined />}>
            日志
          </Button>
          <Popconfirm title="确认删除？" onConfirm={() => message.info('删除功能开发中')}>
            <Button type="text" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>爬虫管理</h2>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => message.info('新建任务功能开发中')}
        >
          新建任务
        </Button>
      </div>

      <Card>
        <Table
          columns={columns}
          dataSource={data?.data?.items || []}
          rowKey="id"
          loading={isLoading}
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
