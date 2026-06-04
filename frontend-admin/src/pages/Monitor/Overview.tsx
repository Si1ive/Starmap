import { Card, Row, Col, Statistic, Table, Tag } from 'antd'
import {
  ApiOutlined,
  DatabaseOutlined,
  WarningOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getApiMonitor, getDatabaseMonitor, getErrorLogs } from '@/api'

const MonitorOverview = () => {
  const { data: apiData } = useQuery({
    queryKey: ['apiMonitor'],
    queryFn: getApiMonitor,
  })

  const { data: dbData } = useQuery({
    queryKey: ['dbMonitor'],
    queryFn: getDatabaseMonitor,
  })

  const { data: errorData } = useQuery({
    queryKey: ['errorLogs'],
    queryFn: () => getErrorLogs({ page: 1, page_size: 5 }),
  })

  const errorColumns = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      width: 180,
    },
    {
      title: '级别',
      dataIndex: 'level',
      width: 100,
      render: (level: string) => {
        const colorMap: Record<string, string> = {
          ERROR: 'red',
          WARNING: 'orange',
          INFO: 'blue',
        }
        return <Tag color={colorMap[level] || 'default'}>{level}</Tag>
      },
    },
    {
      title: '服务',
      dataIndex: 'service',
      width: 120,
    },
    {
      title: '错误信息',
      dataIndex: 'message',
      ellipsis: true,
    },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>系统监控</h2>

      {/* 概览统计 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="API总请求数（1小时）"
              value={apiData?.data?.total_requests as number || 0}
              prefix={<ApiOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="平均响应时间"
              value={apiData?.data?.avg_response_time as number || 0}
              suffix="ms"
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="数据库连接状态"
              value={dbData?.data?.status === 'connected' ? '正常' : '异常'}
              valueStyle={{ color: dbData?.data?.status === 'connected' ? '#52c41a' : '#ff4d4f' }}
              prefix={<DatabaseOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="错误数（24小时）"
              value={errorData?.data?.total as number || 0}
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* API性能 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={12}>
          <Card title="API性能概览">
            <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
              图表数据加载中...
            </div>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="数据库状态">
            <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
              监控数据加载中...
            </div>
          </Card>
        </Col>
      </Row>

      {/* 错误日志 */}
      <Card title="最近错误日志">
        <Table
          columns={errorColumns}
          dataSource={(errorData?.data?.items as Record<string, unknown>[] | undefined) || []}
          rowKey="id"
          pagination={false}
          size="small"
        />
      </Card>
    </div>
  )
}

export default MonitorOverview
