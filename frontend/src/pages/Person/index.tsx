import React, { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card,
  Descriptions,
  Tag,
  Timeline,
  List,
  Avatar,
  Button,
  Typography,
  message,
  Tabs
} from 'antd'
import {
  UserOutlined,
  ArrowLeftOutlined,
  ShareAltOutlined,
  TrophyOutlined,
  CalendarOutlined
} from '@ant-design/icons'
import { getPersonDetail } from '@/api/person'
import { useAppStore } from '@/store'
import Loading from '@/components/Loading'
import type { IPerson, IWork, IRelation } from '@/types'

const { Title, Text } = Typography
const { TabPane } = Tabs

interface PersonDetail extends IPerson {
  biography?: string
  works?: IWork[]
  relations?: IRelation[]
  awards?: Array<{
    name: string
    category: string
    year: number
  }>
  timeline?: Array<{
    date: string
    event: string
    type: string
  }>
}

const PersonPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const setCurrentPerson = useAppStore((state) => state.setCurrentPerson)

  const [person, setPerson] = useState<PersonDetail | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchPersonDetail = useCallback(async () => {
    if (!id) return

    setLoading(true)
    try {
      const response = await getPersonDetail(id)
      const data = (response as any)?.data || response
      setPerson(data)
      setCurrentPerson({ id: data.id, name: data.name })
    } catch (error) {
      console.error('获取人物详情错误:', error)
      message.error('获取人物详情失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [id, setCurrentPerson])

  useEffect(() => {
    fetchPersonDetail()
  }, [fetchPersonDetail])

  const handleBack = useCallback(() => {
    navigate(-1)
  }, [navigate])

  const handleViewGraph = useCallback(() => {
    if (id) {
      navigate(`/graph/${id}`)
    }
  }, [id, navigate])

  return (
    <Loading loading={loading} empty={!person && !loading}>
      {person && (
        <div style={{ maxWidth: 1000, margin: '0 auto' }}>
          {/* 顶部导航 */}
          <div style={{ marginBottom: 24 }}>
            <Button icon={<ArrowLeftOutlined />} onClick={handleBack}>
              返回
            </Button>
          </div>

          {/* 人物头部信息 */}
          <Card style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 24 }}>
              <Avatar
                size={120}
                src={person.avatar}
                icon={<UserOutlined />}
                style={{ backgroundColor: '#1890ff', flexShrink: 0 }}
              />
              <div style={{ flex: 1 }}>
                <div style={{ marginBottom: 8 }}>
                  <Title level={3} style={{ margin: 0, display: 'inline' }}>
                    {person.name}
                  </Title>
                  {person.name_en && (
                    <Text type="secondary" style={{ marginLeft: 12, fontSize: 16 }}>
                      {person.name_en}
                    </Text>
                  )}
                </div>
                <div style={{ marginBottom: 12 }}>
                  {person.categories.map((cat) => (
                    <Tag key={cat} color="blue" style={{ marginBottom: 4 }}>
                      {cat}
                    </Tag>
                  ))}
                </div>
                <Text type="secondary">{person.summary}</Text>
                <div style={{ marginTop: 12 }}>
                  <Button
                    type="primary"
                    icon={<ShareAltOutlined />}
                    onClick={handleViewGraph}
                    style={{ marginRight: 8 }}
                  >
                    查看关系图谱
                  </Button>
                </div>
              </div>
            </div>
          </Card>

          {/* 详细信息标签页 */}
          <Card>
            <Tabs defaultActiveKey="basic">
              <TabPane tab="基本信息" key="basic">
                <Descriptions bordered column={{ xs: 1, sm: 2, md: 2 }}>
                  <Descriptions.Item label="姓名">{person.name}</Descriptions.Item>
                  {person.name_en && (
                    <Descriptions.Item label="英文名">{person.name_en}</Descriptions.Item>
                  )}
                  {person.birth_date && (
                    <Descriptions.Item label="出生日期">{person.birth_date}</Descriptions.Item>
                  )}
                  {person.birth_place && (
                    <Descriptions.Item label="出生地">{person.birth_place}</Descriptions.Item>
                  )}
                  {person.nationality && (
                    <Descriptions.Item label="国籍">{person.nationality}</Descriptions.Item>
                  )}
                  {person.gender && (
                    <Descriptions.Item label="性别">
                      {person.gender === 'male' ? '男' : '女'}
                    </Descriptions.Item>
                  )}
                  {person.height && (
                    <Descriptions.Item label="身高">{person.height} cm</Descriptions.Item>
                  )}
                </Descriptions>
                {person.biography && (
                  <div style={{ marginTop: 24 }}>
                    <Title level={5}>人物简介</Title>
                    <Text>{person.biography}</Text>
                  </div>
                )}
              </TabPane>

              <TabPane
                tab={
                  <span>
                    <CalendarOutlined /> 作品
                    {person.works && person.works.length > 0 && (
                      <Tag color="blue" style={{ marginLeft: 4 }}>
                        {person.works.length}
                      </Tag>
                    )}
                  </span>
                }
                key="works"
              >
                {person.works && person.works.length > 0 ? (
                  <List
                    grid={{ gutter: 16, xs: 1, sm: 2, md: 3 }}
                    dataSource={person.works}
                    renderItem={(work: IWork) => (
                      <List.Item>
                        <Card size="small" title={work.title}>
                          <div>
                            <Tag color="green">{work.type}</Tag>
                            {work.release_date && (
                              <Text type="secondary" style={{ marginLeft: 8 }}>
                                {work.release_date}
                              </Text>
                            )}
                          </div>
                          {work.rating && (
                            <div style={{ marginTop: 8 }}>
                              <Text type="warning">评分: {work.rating}</Text>
                            </div>
                          )}
                          {work.summary && (
                            <Text type="secondary" ellipsis style={{ marginTop: 8, display: 'block' }}>
                              {work.summary}
                            </Text>
                          )}
                        </Card>
                      </List.Item>
                    )}
                  />
                ) : (
                  <Text type="secondary">暂无作品信息</Text>
                )}
              </TabPane>

              <TabPane
                tab={
                  <span>
                    <ShareAltOutlined /> 关系
                    {person.relations && person.relations.length > 0 && (
                      <Tag color="blue" style={{ marginLeft: 4 }}>
                        {person.relations.length}
                      </Tag>
                    )}
                  </span>
                }
                key="relations"
              >
                {person.relations && person.relations.length > 0 ? (
                  <List
                    grid={{ gutter: 16, xs: 1, sm: 2, md: 3 }}
                    dataSource={person.relations}
                    renderItem={(relation: IRelation) => (
                      <List.Item>
                        <Card
                          size="small"
                          hoverable
                          onClick={() => navigate(`/person/${relation.person.id}`)}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                            <Avatar
                              src={relation.person.avatar}
                              icon={<UserOutlined />}
                              style={{ backgroundColor: '#1890ff' }}
                            />
                            <div>
                              <div style={{ fontWeight: 500 }}>{relation.person.name}</div>
                              <Tag size="small" color="purple">
                                {relation.description || relation.type}
                              </Tag>
                            </div>
                          </div>
                        </Card>
                      </List.Item>
                    )}
                  />
                ) : (
                  <Text type="secondary">暂无关系信息</Text>
                )}
              </TabPane>

              <TabPane
                tab={
                  <span>
                    <TrophyOutlined /> 荣誉
                    {person.awards && person.awards.length > 0 && (
                      <Tag color="blue" style={{ marginLeft: 4 }}>
                        {person.awards.length}
                      </Tag>
                    )}
                  </span>
                }
                key="awards"
              >
                {person.awards && person.awards.length > 0 ? (
                  <List
                    dataSource={person.awards}
                    renderItem={(award) => (
                      <List.Item>
                        <div>
                          <Text strong>{award.name}</Text>
                          <Tag color="gold" style={{ marginLeft: 8 }}>
                            {award.category}
                          </Tag>
                          <Text type="secondary" style={{ marginLeft: 8 }}>
                            {award.year}年
                          </Text>
                        </div>
                      </List.Item>
                    )}
                  />
                ) : (
                  <Text type="secondary">暂无荣誉信息</Text>
                )}
              </TabPane>

              <TabPane tab="时间线" key="timeline">
                {person.timeline && person.timeline.length > 0 ? (
                  <Timeline
                    mode="left"
                    items={person.timeline.map((item) => ({
                      label: item.date,
                      children: (
                        <div>
                          <Text strong>{item.event}</Text>
                          <Tag
                            size="small"
                            color={item.type === 'career' ? 'blue' : 'green'}
                            style={{ marginLeft: 8 }}
                          >
                            {item.type === 'career' ? '事业' : '生活'}
                          </Tag>
                        </div>
                      )
                    }))}
                  />
                ) : (
                  <Text type="secondary">暂无时间线信息</Text>
                )}
              </TabPane>
            </Tabs>
          </Card>
        </div>
      )}
    </Loading>
  )
}

export default PersonPage
