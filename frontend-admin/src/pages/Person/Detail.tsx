import { useParams, useNavigate } from 'react-router-dom'
import { Card, Descriptions, Tag, Button, Spin, Avatar, Tabs } from 'antd'
import { EditOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getPersonDetail } from '@/api'

const { TabPane } = Tabs

const PersonDetail = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['person', id],
    queryFn: () => getPersonDetail(id!),
    enabled: !!id,
  })

  const person = data?.data

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '100px 0' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  if (!person) {
    return <div>艺人不存在</div>
  }

  const statusMap: Record<string, { color: string; text: string }> = {
    complete: { color: 'success', text: '完整' },
    partial: { color: 'warning', text: '部分' },
    pending: { color: 'processing', text: '待审核' },
    processing: { color: 'default', text: '处理中' },
  }

  const status = statusMap[person.status] || { color: 'default', text: person.status }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/persons')}>
            返回
          </Button>
          <h2 style={{ margin: 0 }}>艺人详情</h2>
        </div>
        <Button
          type="primary"
          icon={<EditOutlined />}
          onClick={() => navigate(`/admin/persons/${id}/edit`)}
        >
          编辑
        </Button>
      </div>

      <Card style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', gap: 24, marginBottom: 24 }}>
          <Avatar src={person.avatar} size={120} />
          <div>
            <h1 style={{ margin: '0 0 8px 0' }}>
              {person.name}
              {person.name_en && <span style={{ color: '#666', marginLeft: 12 }}>{person.name_en}</span>}
            </h1>
            <div style={{ marginBottom: 8 }}>
              {person.categories?.map((cat) => (
                <Tag key={cat}>{cat}</Tag>
              ))}
              <Tag color={status.color}>{status.text}</Tag>
            </div>
            <p style={{ color: '#666' }}>{person.summary}</p>
          </div>
        </div>
      </Card>

      <Tabs defaultActiveKey="basic">
        <TabPane tab="基本信息" key="basic">
          <Card>
            <Descriptions bordered column={2}>
              <Descriptions.Item label="ID">{person.id}</Descriptions.Item>
              <Descriptions.Item label="姓名">{person.name}</Descriptions.Item>
              <Descriptions.Item label="英文名">{person.name_en || '-'}</Descriptions.Item>
              <Descriptions.Item label="性别">
                {person.gender === 'male' ? '男' : person.gender === 'female' ? '女' : '未知'}
              </Descriptions.Item>
              <Descriptions.Item label="出生日期">{person.birth_date || '-'}</Descriptions.Item>
              <Descriptions.Item label="出生地点">{person.birth_place || '-'}</Descriptions.Item>
              <Descriptions.Item label="国籍">{person.nationality || '-'}</Descriptions.Item>
              <Descriptions.Item label="身高">{person.height ? `${person.height}cm` : '-'}</Descriptions.Item>
              <Descriptions.Item label="数据来源">{person.source}</Descriptions.Item>
              <Descriptions.Item label="创建时间">{person.created_at}</Descriptions.Item>
              <Descriptions.Item label="更新时间">{person.updated_at}</Descriptions.Item>
              <Descriptions.Item label="分类">
                {person.categories?.map((cat) => (
                  <Tag key={cat}>{cat}</Tag>
                ))}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </TabPane>

        <TabPane tab="详细传记" key="biography">
          <Card>
            <div
              dangerouslySetInnerHTML={{
                __html: person.biography || '<p style="color: #999">暂无传记信息</p>',
              }}
            />
          </Card>
        </TabPane>

        <TabPane tab="作品列表" key="works">
          <Card>
            <p style={{ color: '#999', textAlign: 'center', padding: '40px 0' }}>作品数据加载中...</p>
          </Card>
        </TabPane>

        <TabPane tab="关系图谱" key="relations">
          <Card>
            <p style={{ color: '#999', textAlign: 'center', padding: '40px 0' }}>关系数据加载中...</p>
          </Card>
        </TabPane>

        <TabPane tab="编辑历史" key="history">
          <Card>
            <p style={{ color: '#999', textAlign: 'center', padding: '40px 0' }}>暂无编辑记录</p>
          </Card>
        </TabPane>
      </Tabs>
    </div>
  )
}

export default PersonDetail
