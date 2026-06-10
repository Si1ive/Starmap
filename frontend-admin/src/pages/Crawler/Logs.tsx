import { useState } from 'react'
import { Card, Table, Tag, Select, Input, Row, Col, Statistic, Space, Button, Tooltip, Modal, message } from 'antd'
import { SearchOutlined, ReloadOutlined, FileOutlined, CheckCircleOutlined, CloseCircleOutlined, RedoOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import adminClient from '@/api/client'

const getFileLogs = (params: Record<string, unknown>) =>
  adminClient.get('/crawler/file-logs', { params })

const getFileLogRepos = () =>
  adminClient.get('/crawler/file-logs/repos')

const retryFileDownloads = (fileIds: string[]) =>
  adminClient.post('/crawler/file-logs/retry', fileIds)

const formatFileSize = (bytes?: number) => {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const statusConfig: Record<string, { color: string; text: string }> = {
  downloaded: { color: 'green', text: '已下载' },
  processing: { color: 'blue', text: '处理中' },
  processed: { color: 'purple', text: '已处理' },
  failed: { color: 'red', text: '失败' },
  skipped: { color: 'default', text: '跳过' },
}

const CrawlerLogs = () => {
  const queryClient = useQueryClient()
  const [params, setParams] = useState<Record<string, unknown>>({
    page: 1,
    page_size: 50,
  })
  const [searchText, setSearchText] = useState('')
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const retryMutation = useMutation({
    mutationFn: retryFileDownloads,
    onSuccess: (res: any) => {
      const d = res?.data
      message.success(`重试完成：成功 ${d?.success_count ?? 0} 个，失败 ${d?.fail_count ?? 0} 个`)
      setSelectedRowKeys([])
      queryClient.invalidateQueries({ queryKey: ['fileLogs'] })
    },
    onError: () => message.error('重试请求失败'),
  })

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['fileLogs', params],
    queryFn: () => getFileLogs(params),
  })

  const { data: reposData } = useQuery({
    queryKey: ['fileLogRepos'],
    queryFn: getFileLogRepos,
  })

  const logs = (data?.data?.items || []) as any[]
  const total = data?.data?.total || 0
  const repos = (reposData?.data || []) as string[]

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '任务ID',
      dataIndex: 'task_id',
      width: 140,
      ellipsis: true,
      render: (v: string) => v ? (
        <Tooltip title={v}>
          <Tag color="blue">{v}</Tag>
        </Tooltip>
      ) : '-',
    },
    {
      title: '文件名',
      dataIndex: 'file_name',
      width: 250,
      ellipsis: true,
      render: (name: string, record: any) => (
        <Tooltip title={record.file_path}>
          <span>
            <FileOutlined style={{ marginRight: 4, color: '#1890ff' }} />
            {name}
          </span>
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
      width: 90,
      render: (s: string) => {
        const config = statusConfig[s] || { color: 'default', text: s }
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
      title: '下载链接',
      dataIndex: 'download_url',
      width: 80,
      render: (url: string) => url ? (
        <a href={url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12 }}>
          查看
        </a>
      ) : '-',
    },
  ]

  // 本地搜索过滤
  const filteredLogs = searchText.trim()
    ? logs.filter((log) => {
        const kw = searchText.trim().toLowerCase()
        return [
          log.file_name,
          log.repo_name,
          log.file_path,
          log.task_id,
          log.error_detail,
        ]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(kw))
      })
    : logs

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>文件爬取日志</h2>
        <Space>
          {selectedRowKeys.length > 0 && (
            <Button
              type="primary"
              icon={<RedoOutlined />}
              loading={retryMutation.isPending}
              onClick={() => {
                Modal.confirm({
                  title: '确认重试下载',
                  content: `即将重试下载 ${selectedRowKeys.length} 个文件，确定继续？`,
                  onOk: () => retryMutation.mutate(selectedRowKeys as string[]),
                })
              }}
            >
              重试下载 ({selectedRowKeys.length})
            </Button>
          )}
          <Button icon={<ReloadOutlined />} onClick={() => refetch()}>
            刷新
          </Button>
        </Space>
      </div>

      {/* 统计 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={8}>
          <Card size="small">
            <Statistic title="总文件数" value={total} prefix={<FileOutlined style={{ color: '#1890ff' }} />} />
          </Card>
        </Col>
        <Col xs={8}>
          <Card size="small">
            <Statistic title="成功" value={data?.data?.success_count ?? 0} valueStyle={{ color: '#52c41a' }} prefix={<CheckCircleOutlined />} />
          </Card>
        </Col>
        <Col xs={8}>
          <Card size="small">
            <Statistic title="失败" value={data?.data?.failed_count ?? 0} valueStyle={{ color: '#ff4d4f' }} prefix={<CloseCircleOutlined />} />
          </Card>
        </Col>
      </Row>

      {/* 筛选 */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            value={params.status as string || 'all'}
            onChange={(v) => setParams((p) => ({ ...p, page: 1, status: v === 'all' ? undefined : v }))}
            style={{ width: 120 }}
            options={[
              { label: '全部状态', value: 'all' },
              { label: '已下载', value: 'downloaded' },
              { label: '处理中', value: 'processing' },
              { label: '已处理', value: 'processed' },
              { label: '失败', value: 'failed' },
              { label: '跳过', value: 'skipped' },
            ]}
          />
          <Select
            value={params.repo_name as string || 'all'}
            onChange={(v) => setParams((p) => ({ ...p, page: 1, repo_name: v === 'all' ? undefined : v }))}
            style={{ width: 200 }}
            options={[
              { label: '全部仓库', value: 'all' },
              ...repos.map((r) => ({ label: r, value: r })),
            ]}
          />
          <Select
            value={params.file_type as string || 'all'}
            onChange={(v) => setParams((p) => ({ ...p, page: 1, file_type: v === 'all' ? undefined : v }))}
            style={{ width: 120 }}
            options={[
              { label: '全部类型', value: 'all' },
              { label: 'PDF', value: 'pdf' },
              { label: 'Word', value: 'doc' },
              { label: 'PPT', value: 'ppt' },
              { label: 'Markdown', value: 'md' },
            ]}
          />
          <Input
            placeholder="搜索文件名、仓库、路径、错误信息"
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{ width: 300 }}
            allowClear
          />
        </Space>
      </Card>

      {/* 日志列表 */}
      <Card>
        <Table
          columns={columns}
          dataSource={filteredLogs as any[]}
          rowKey="id"
          loading={isLoading}
          size="small"
          scroll={{ x: 1200 }}
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            getCheckboxProps: (record: any) => ({
              disabled: !record.download_url,
            }),
          }}
          pagination={{
            current: params.page as number || 1,
            pageSize: params.page_size as number || 50,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
          }}
          onChange={(pagination) =>
            setParams((p) => ({
              ...p,
              page: pagination.current || 1,
              page_size: pagination.pageSize || 50,
            }))
          }
        />
      </Card>
    </div>
  )
}

export default CrawlerLogs
