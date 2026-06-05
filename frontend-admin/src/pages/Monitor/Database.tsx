import { Row, Col, Card, Statistic, Table, Tag, Descriptions, Progress } from 'antd'
import {
  DatabaseOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getDatabaseMonitor } from '@/api'

interface DBStatus {
  name: string
  type: string
  status: 'connected' | 'disconnected' | 'warning'
  version: string
  uptime: string
  connections: number
  max_connections: number
  size: string
  operations_per_sec: number
  cache_hit_rate: number
  last_check: string
}

const DatabaseMonitor = () => {
  const { data } = useQuery({
    queryKey: ['monitorDatabase'],
    queryFn: getDatabaseMonitor,
    refetchInterval: 30000,
  })

  const dbData = (data?.data || {}) as Record<string, any>

  const databases: DBStatus[] = (dbData.databases || [
    {
      name: 'Neo4j',
      type: '图数据库',
      status: 'connected',
      version: '5.15.0',
      uptime: '15天 3小时',
      connections: 12,
      max_connections: 100,
      size: '2.3 GB',
      operations_per_sec: 156,
      cache_hit_rate: 92.5,
      last_check: '2024-01-07 15:30:00',
    },
    {
      name: 'Redis',
      type: '缓存',
      status: 'connected',
      version: '7.2.3',
      uptime: '30天 12小时',
      connections: 8,
      max_connections: 50,
      size: '256 MB',
      operations_per_sec: 2300,
      cache_hit_rate: 98.7,
      last_check: '2024-01-07 15:30:00',
    },
    {
      name: 'ChromaDB',
      type: '向量数据库',
      status: 'connected',
      version: '0.4.22',
      uptime: '10天 8小时',
      connections: 5,
      max_connections: 20,
      size: '1.8 GB',
      operations_per_sec: 45,
      cache_hit_rate: 85.3,
      last_check: '2024-01-07 15:30:00',
    },
    {
      name: 'MySQL',
      type: '关系数据库',
      status: 'connected',
      version: '8.0.35',
      uptime: '45天 6小时',
      connections: 18,
      max_connections: 200,
      size: '520 MB',
      operations_per_sec: 320,
      cache_hit_rate: 96.2,
      last_check: '2024-01-07 15:30:00',
    },
  ]) as DBStatus[]

  const getStatusIcon = (status: string) => {
    if (status === 'connected') return <CheckCircleOutlined style={{ color: '#52c41a' }} />
    if (status === 'warning') return <ExclamationCircleOutlined style={{ color: '#fa8c16' }} />
    return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
  }

  const getStatusTag = (status: string) => {
    if (status === 'connected') return <Tag color="success">已连接</Tag>
    if (status === 'warning') return <Tag color="warning">警告</Tag>
    return <Tag color="error">断开</Tag>
  }

  // 性能指标列
  const performanceColumns = [
    { title: '数据库', dataIndex: 'name', width: 100 },
    { title: '类型', dataIndex: 'type', width: 100 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (s: string) => getStatusTag(s),
    },
    { title: '版本', dataIndex: 'version', width: 100 },
    { title: '运行时间', dataIndex: 'uptime', width: 130 },
    {
      title: '连接数',
      dataIndex: 'connections',
      width: 120,
      render: (v: number, r: DBStatus) => (
        <span>
          {v}/{r.max_connections}
          <Progress
            percent={(v / r.max_connections) * 100}
            size="small"
            status={v / r.max_connections > 0.8 ? 'exception' : 'normal'}
            style={{ marginLeft: 8, width: 60 }}
          />
        </span>
      ),
    },
    { title: '数据量', dataIndex: 'size', width: 100 },
    {
      title: 'OPS/s',
      dataIndex: 'operations_per_sec',
      width: 100,
    },
    {
      title: '缓存命中率',
      dataIndex: 'cache_hit_rate',
      width: 120,
      render: (v: number) => (
        <Progress
          percent={v}
          size="small"
          status={v < 80 ? 'exception' : v < 90 ? 'active' : 'success'}
          format={(p) => `${p}%`}
        />
      ),
    },
  ]

  // Neo4j 详细信息
  const neo4jDetail = (dbData.neo4j_detail || {
    node_count: 12580,
    relationship_count: 45600,
    label_distribution: [
      { label: 'Person', count: 8900 },
      { label: 'Work', count: 3200 },
      { label: 'Organization', count: 480 },
      { label: 'Event', count: 0 },
    ],
    query_count_24h: 45230,
    avg_query_time: 85,
    slow_queries_24h: 12,
  }) as Record<string, any>

  // Redis 详细信息
  const redisDetail = (dbData.redis_detail || {
    key_count: 125000,
    memory_used: '256 MB',
    memory_limit: '512 MB',
    hit_rate: 98.7,
    miss_rate: 1.3,
    evicted_keys: 0,
    key_types: [
      { type: 'string', count: 80000 },
      { type: 'hash', count: 25000 },
      { type: 'set', count: 15000 },
      { type: 'zset', count: 5000 },
    ],
  }) as Record<string, any>

  // ChromaDB 详细信息
  const chromaDetail = (dbData.chroma_detail || {
    collection_count: 3,
    vector_count: 156000,
    index_size: '1.8 GB',
    avg_query_time: 45,
    embedding_model: 'text2vec-chinese',
    collections: [
      { name: 'person_knowledge', vectors: 89000, size: '1.2 GB' },
      { name: 'work_description', vectors: 45000, size: '0.4 GB' },
      { name: 'conversation_context', vectors: 22000, size: '0.2 GB' },
    ],
  }) as Record<string, any>

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>数据库监控</h2>

      {/* 总览统计 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="数据库总数"
              value={4}
              prefix={<DatabaseOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="已连接"
              value={databases.filter((d) => d.status === 'connected').length}
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="警告"
              value={databases.filter((d) => d.status === 'warning').length}
              valueStyle={{ color: '#fa8c16' }}
              prefix={<ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="断开"
              value={databases.filter((d) => d.status === 'disconnected').length}
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<CloseCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 性能概览表 */}
      <Card title="数据库性能概览" style={{ marginBottom: 24 }}>
        <Table
          columns={performanceColumns}
          dataSource={databases}
          rowKey="name"
          pagination={false}
          size="small"
        />
      </Card>

      {/* Neo4j 详情 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={8}>
          <Card title="Neo4j 图数据库" extra={getStatusIcon('connected')}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="节点总数">{neo4jDetail.node_count}</Descriptions.Item>
              <Descriptions.Item label="关系总数">{neo4jDetail.relationship_count}</Descriptions.Item>
              <Descriptions.Item label="24h查询量">{neo4jDetail.query_count_24h}</Descriptions.Item>
              <Descriptions.Item label="平均查询时间">{neo4jDetail.avg_query_time}ms</Descriptions.Item>
              <Descriptions.Item label="24h慢查询">{neo4jDetail.slow_queries_24h}</Descriptions.Item>
            </Descriptions>
            <div style={{ marginTop: 12 }}>
              <div style={{ fontWeight: 'bold', marginBottom: 8 }}>标签分布</div>
              {neo4jDetail.label_distribution.map((item: any) => (
                <div key={item.label} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span>{item.label}</span>
                  <Tag color="blue">{item.count}</Tag>
                </div>
              ))}
            </div>
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="Redis 缓存" extra={getStatusIcon('connected')}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="Key总数">{redisDetail.key_count}</Descriptions.Item>
              <Descriptions.Item label="内存使用">{redisDetail.memory_used} / {redisDetail.memory_limit}</Descriptions.Item>
              <Descriptions.Item label="命中率">
                <Progress percent={redisDetail.hit_rate} size="small" status="success" format={(p) => `${p}%`} />
              </Descriptions.Item>
              <Descriptions.Item label="未命中率">{redisDetail.miss_rate}%</Descriptions.Item>
              <Descriptions.Item label="淘汰Key">{redisDetail.evicted_keys}</Descriptions.Item>
            </Descriptions>
            <div style={{ marginTop: 12 }}>
              <div style={{ fontWeight: 'bold', marginBottom: 8 }}>Key类型分布</div>
              {redisDetail.key_types.map((item: any) => (
                <div key={item.type} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span>{item.type}</span>
                  <Tag color="purple">{item.count}</Tag>
                </div>
              ))}
            </div>
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="ChromaDB 向量数据库" extra={getStatusIcon('connected')}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="集合数">{chromaDetail.collection_count}</Descriptions.Item>
              <Descriptions.Item label="向量总数">{chromaDetail.vector_count}</Descriptions.Item>
              <Descriptions.Item label="索引大小">{chromaDetail.index_size}</Descriptions.Item>
              <Descriptions.Item label="平均查询时间">{chromaDetail.avg_query_time}ms</Descriptions.Item>
              <Descriptions.Item label="Embedding模型">{chromaDetail.embedding_model}</Descriptions.Item>
            </Descriptions>
            <div style={{ marginTop: 12 }}>
              <div style={{ fontWeight: 'bold', marginBottom: 8 }}>集合列表</div>
              {chromaDetail.collections.map((item: any) => (
                <div key={item.name} style={{ marginBottom: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>{item.name}</span>
                    <span style={{ color: '#666' }}>{item.size}</span>
                  </div>
                  <Progress percent={(item.vectors / chromaDetail.vector_count) * 100} size="small" />
                </div>
              ))}
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default DatabaseMonitor