import { useState } from 'react'
import { Card, Table, Tag, Button, Modal, Descriptions, Select, Space, Input, Row, Col, Statistic, Badge } from 'antd'
import { SearchOutlined, ExclamationCircleOutlined, WarningOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getErrorLogs } from '@/api'

interface ErrorLog {
  id: string
  timestamp: string
  level: 'error' | 'warning' | 'critical'
  module: string
  message: string
  endpoint: string
  stack_trace: string
  request_id: string
  user_id: string | null
  resolved: boolean
  count: number
}

const MonitorErrors = () => {
  const [selectedLog, setSelectedLog] = useState<ErrorLog | null>(null)
  const [filterLevel, setFilterLevel] = useState<string>('all')
  const [filterModule, setFilterModule] = useState<string>('all')
  const [filterResolved, setFilterResolved] = useState<string>('all')
  const [searchText, setSearchText] = useState('')

  const { data } = useQuery({
    queryKey: ['monitorErrors'],
    queryFn: () => getErrorLogs(),
  })

  const errorData = (data?.data || {}) as Record<string, any>

  // 统计
  const stats = (errorData.stats || {}) as Record<string, number>

  // 错误列表
  const rawLogs: ErrorLog[] = (errorData.logs || []) as ErrorLog[]

  // 过滤
  const filteredLogs = rawLogs.filter((log) => {
    if (filterLevel !== 'all' && log.level !== filterLevel) return false
    if (filterModule !== 'all' && log.module !== filterModule) return false
    if (filterResolved === 'unresolved' && log.resolved) return false
    if (filterResolved === 'resolved' && !log.resolved) return false
    if (searchText && !log.message.toLowerCase().includes(searchText.toLowerCase())) return false
    return true
  })

  const columns = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      width: 170,
      sorter: (a: ErrorLog, b: ErrorLog) => a.timestamp.localeCompare(b.timestamp),
    },
    {
      title: '级别',
      dataIndex: 'level',
      width: 90,
      render: (level: string) => {
        const config: Record<string, { color: string; text: string }> = {
          critical: { color: '#ff4d4f', text: '严重' },
          error: { color: '#ff7875', text: '错误' },
          warning: { color: '#fa8c16', text: '警告' },
        }
        const c = config[level] || { color: 'default', text: level }
        return <Tag color={c.color}>{c.text}</Tag>
      },
      filters: [
        { text: '严重', value: 'critical' },
        { text: '错误', value: 'error' },
        { text: '警告', value: 'warning' },
      ],
      onFilter: (value: any, record: ErrorLog) => record.level === value,
    },
    {
      title: '模块',
      dataIndex: 'module',
      width: 100,
      render: (m: string) => <Tag>{m}</Tag>,
    },
    {
      title: '消息',
      dataIndex: 'message',
      ellipsis: true,
    },
    {
      title: '接口',
      dataIndex: 'endpoint',
      width: 200,
      ellipsis: true,
    },
    {
      title: '次数',
      dataIndex: 'count',
      width: 70,
      render: (v: number) => <Badge count={v} style={{ backgroundColor: v > 3 ? '#ff4d4f' : '#fa8c16' }} />,
    },
    {
      title: '状态',
      dataIndex: 'resolved',
      width: 80,
      render: (v: boolean) => v ? <Tag color="success">已解决</Tag> : <Tag color="error">未解决</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: any, record: ErrorLog) => (
        <Button type="link" size="small" onClick={() => setSelectedLog(record)}>
          详情
        </Button>
      ),
    },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>错误日志</h2>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="总错误数"
              value={stats.total_errors}
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="总警告数"
              value={stats.total_warnings}
              valueStyle={{ color: '#fa8c16' }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="未解决"
              value={stats.unresolved}
              valueStyle={{ color: stats.unresolved > 0 ? '#ff4d4f' : '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="今日新增"
              value={stats.today_errors}
            />
          </Card>
        </Col>
      </Row>

      {/* 过滤栏 */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            value={filterLevel}
            onChange={setFilterLevel}
            style={{ width: 120 }}
            options={[
              { label: '全部级别', value: 'all' },
              { label: '严重', value: 'critical' },
              { label: '错误', value: 'error' },
              { label: '警告', value: 'warning' },
            ]}
          />
          <Select
            value={filterModule}
            onChange={setFilterModule}
            style={{ width: 120 }}
            options={[
              { label: '全部模块', value: 'all' },
              { label: 'chat', value: 'chat' },
              { label: 'crawler', value: 'crawler' },
              { label: 'neo4j', value: 'neo4j' },
              { label: 'redis', value: 'redis' },
              { label: 'chromadb', value: 'chromadb' },
              { label: 'auth', value: 'auth' },
            ]}
          />
          <Select
            value={filterResolved}
            onChange={setFilterResolved}
            style={{ width: 120 }}
            options={[
              { label: '全部状态', value: 'all' },
              { label: '未解决', value: 'unresolved' },
              { label: '已解决', value: 'resolved' },
            ]}
          />
          <Input
            placeholder="搜索错误消息"
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{ width: 200 }}
            allowClear
          />
        </Space>
      </Card>

      {/* 错误列表 */}
      <Card>
        <Table
          columns={columns}
          dataSource={filteredLogs}
          rowKey="id"
          size="small"
          pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
        />
      </Card>

      {/* 详情弹窗 */}
      <Modal
        title="错误详情"
        open={!!selectedLog}
        onCancel={() => setSelectedLog(null)}
        footer={null}
        width={700}
      >
        {selectedLog && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="时间">{selectedLog.timestamp}</Descriptions.Item>
            <Descriptions.Item label="级别">
              <Tag color={selectedLog.level === 'critical' ? '#ff4d4f' : selectedLog.level === 'error' ? '#ff7875' : '#fa8c16'}>
                {selectedLog.level === 'critical' ? '严重' : selectedLog.level === 'error' ? '错误' : '警告'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="模块">{selectedLog.module}</Descriptions.Item>
            <Descriptions.Item label="接口">{selectedLog.endpoint}</Descriptions.Item>
            <Descriptions.Item label="请求ID">{selectedLog.request_id}</Descriptions.Item>
            <Descriptions.Item label="用户ID">{selectedLog.user_id || 'N/A'}</Descriptions.Item>
            <Descriptions.Item label="出现次数">{selectedLog.count}</Descriptions.Item>
            <Descriptions.Item label="状态">
              {selectedLog.resolved ? <Tag color="success">已解决</Tag> : <Tag color="error">未解决</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="错误消息" span={2}>
              <div style={{ color: '#ff4d4f', fontWeight: 'bold' }}>{selectedLog.message}</div>
            </Descriptions.Item>
            <Descriptions.Item label="堆栈跟踪" span={2}>
              <pre style={{
                background: '#f5f5f5',
                padding: 12,
                borderRadius: 4,
                fontSize: 12,
                maxHeight: 300,
                overflow: 'auto',
              }}>
                {selectedLog.stack_trace}
              </pre>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  )
}

export default MonitorErrors