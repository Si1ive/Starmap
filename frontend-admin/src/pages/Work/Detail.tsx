import { useParams, useNavigate } from 'react-router-dom'
import {
  Card,
  Descriptions,
  Tag,
  Button,
  Spin,
  Image,
  Tabs,
  Rate,
  Row,
  Col,
  Avatar,
} from 'antd'
import { EditOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getWorkDetail } from '@/api'

const { TabPane } = Tabs

const workTypeMap: Record<string, { color: string; text: string }> = {
  movie: { color: 'blue', text: '电影' },
  tv: { color: 'purple', text: '电视剧' },
  album: { color: 'green', text: '专辑' },
  single: { color: 'orange', text: '单曲' },
  book: { color: 'cyan', text: '书籍' },
}

const statusMap: Record<string, { color: string; text: string }> = {
  complete: { color: 'success', text: '完整' },
  partial: { color: 'warning', text: '部分' },
  pending: { color: 'processing', text: '待审核' },
}

const WorkDetail = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['work', id],
    queryFn: () => getWorkDetail(id!),
    enabled: !!id,
  })

  const work = data?.data

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '100px 0' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  if (!work) {
    return <div>作品不存在</div>
  }

  const typeConfig = workTypeMap[work.type] || { color: 'default', text: work.type }
  const statusConfig = statusMap[work.status] || { color: 'default', text: work.status }

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 24,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/works')}>
            返回
          </Button>
          <h2 style={{ margin: 0 }}>作品详情</h2>
        </div>
        <Button
          type="primary"
          icon={<EditOutlined />}
          onClick={() => navigate(`/admin/works/${id}/edit`)}
        >
          编辑
        </Button>
      </div>

      <Card style={{ marginBottom: 24 }}>
        <Row gutter={24}>
          <Col xs={24} sm={8} md={6} lg={5}>
            {work.cover ? (
              <Image
                src={work.cover}
                style={{ width: '100%', borderRadius: 8 }}
                preview
              />
            ) : (
              <div
                style={{
                  width: '100%',
                  aspectRatio: '3/4',
                  background: '#f0f0f0',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#999',
                  borderRadius: 8,
                }}
              >
                暂无封面
              </div>
            )}
          </Col>
          <Col xs={24} sm={16} md={18} lg={19}>
            <div style={{ marginBottom: 16 }}>
              <h1 style={{ margin: '0 0 8px 0' }}>
                {work.title}
                {work.title_en && (
                  <span style={{ color: '#666', marginLeft: 12, fontSize: 18 }}>
                    {work.title_en}
                  </span>
                )}
              </h1>
              <div>
                <Tag color={typeConfig.color}>{typeConfig.text}</Tag>
                <Tag color={statusConfig.color}>{statusConfig.text}</Tag>
                {work.year && <Tag>{work.year}年</Tag>}
                {work.genres?.map((genre: string) => (
                  <Tag key={genre}>{genre}</Tag>
                ))}
              </div>
            </div>
            {work.rating && (
              <div style={{ marginBottom: 16 }}>
                <Rate disabled defaultValue={work.rating / 2} allowHalf />
                <span style={{ marginLeft: 8, color: '#666' }}>{work.rating}分</span>
              </div>
            )}
            <p style={{ color: '#666', lineHeight: 1.8 }}>{work.summary || work.description}</p>
          </Col>
        </Row>
      </Card>

      <Tabs defaultActiveKey="basic">
        <TabPane tab="基本信息" key="basic">
          <Card>
            <Descriptions bordered column={2}>
              <Descriptions.Item label="ID">{work.id}</Descriptions.Item>
              <Descriptions.Item label="标题">{work.title}</Descriptions.Item>
              {work.title_en && (
                <Descriptions.Item label="英文标题">{work.title_en}</Descriptions.Item>
              )}
              <Descriptions.Item label="类型">
                <Tag color={typeConfig.color}>{typeConfig.text}</Tag>
              </Descriptions.Item>
              {work.year && <Descriptions.Item label="年份">{work.year}</Descriptions.Item>}
              {work.release_date && (
                <Descriptions.Item label="发行日期">{work.release_date}</Descriptions.Item>
              )}
              {work.status && (
                <Descriptions.Item label="状态">
                  <Tag color={statusConfig.color}>{statusConfig.text}</Tag>
                </Descriptions.Item>
              )}
              {work.source && (
                <Descriptions.Item label="数据来源">{work.source}</Descriptions.Item>
              )}
              {work.created_at && (
                <Descriptions.Item label="创建时间">{work.created_at}</Descriptions.Item>
              )}
              {work.updated_at && (
                <Descriptions.Item label="更新时间">{work.updated_at}</Descriptions.Item>
              )}
            </Descriptions>
          </Card>
        </TabPane>

        {/* 类型特有信息 */}
        {work.type === 'movie' && (
          <TabPane tab="电影信息" key="movie">
            <Card>
              <Descriptions bordered column={2}>
                {work.director && (
                  <Descriptions.Item label="导演">
                    {work.director.join('、')}
                  </Descriptions.Item>
                )}
                {work.actors && (
                  <Descriptions.Item label="演员">
                    {work.actors.join('、')}
                  </Descriptions.Item>
                )}
                {work.box_office && (
                  <Descriptions.Item label="票房">
                    {work.box_office.toLocaleString()} 元
                  </Descriptions.Item>
                )}
              </Descriptions>
            </Card>
          </TabPane>
        )}

        {work.type === 'tv' && (
          <TabPane tab="电视剧信息" key="tv">
            <Card>
              <Descriptions bordered column={2}>
                {work.director && (
                  <Descriptions.Item label="导演">
                    {work.director.join('、')}
                  </Descriptions.Item>
                )}
                {work.actors && (
                  <Descriptions.Item label="演员">
                    {work.actors.join('、')}
                  </Descriptions.Item>
                )}
                {work.episodes && (
                  <Descriptions.Item label="集数">{work.episodes}集</Descriptions.Item>
                )}
                {work.platform && (
                  <Descriptions.Item label="播出平台">{work.platform}</Descriptions.Item>
                )}
              </Descriptions>
            </Card>
          </TabPane>
        )}

        {work.type === 'album' && (
          <TabPane tab="专辑信息" key="album">
            <Card>
              <Descriptions bordered column={2}>
                {work.artist && (
                  <Descriptions.Item label="歌手">
                    {work.artist.join('、')}
                  </Descriptions.Item>
                )}
                {work.record_company && (
                  <Descriptions.Item label="唱片公司">
                    {work.record_company}
                  </Descriptions.Item>
                )}
                {work.track_list && (
                  <Descriptions.Item label="曲目列表">
                    <ol>
                      {work.track_list.map((track: string, index: number) => (
                        <li key={index}>{track}</li>
                      ))}
                    </ol>
                  </Descriptions.Item>
                )}
              </Descriptions>
            </Card>
          </TabPane>
        )}

        {work.type === 'book' && (
          <TabPane tab="书籍信息" key="book">
            <Card>
              <Descriptions bordered column={2}>
                {work.author && (
                  <Descriptions.Item label="作者">
                    {work.author.join('、')}
                  </Descriptions.Item>
                )}
                {work.publisher && (
                  <Descriptions.Item label="出版社">{work.publisher}</Descriptions.Item>
                )}
                {work.isbn && (
                  <Descriptions.Item label="ISBN">{work.isbn}</Descriptions.Item>
                )}
              </Descriptions>
            </Card>
          </TabPane>
        )}

        <TabPane tab="关联艺人" key="persons">
          <Card>
            {work.related_persons && work.related_persons.length > 0 ? (
              <Row gutter={[16, 16]}>
                {work.related_persons.map((person: any) => (
                  <Col key={person.id} xs={24} sm={12} md={8} lg={6}>
                    <Card
                      size="small"
                      hoverable
                      onClick={() => navigate(`/admin/persons/${person.id}`)}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <Avatar size={40}>{person.name?.[0]}</Avatar>
                        <div>
                          <div style={{ fontWeight: 500 }}>{person.name}</div>
                          <Tag>{person.role}</Tag>
                        </div>
                      </div>
                    </Card>
                  </Col>
                ))}
              </Row>
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
                暂无关联艺人
              </div>
            )}
          </Card>
        </TabPane>

        <TabPane tab="标签" key="tags">
          <Card>
            {work.tags && work.tags.length > 0 ? (
              <div>
                {work.tags.map((tag: string) => (
                  <Tag key={tag}>{tag}</Tag>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
                暂无标签
              </div>
            )}
          </Card>
        </TabPane>
      </Tabs>
    </div>
  )
}

export default WorkDetail
