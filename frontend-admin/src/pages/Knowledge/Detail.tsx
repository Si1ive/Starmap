import { useParams, useNavigate } from 'react-router-dom'
import { Card, Tag, Button, Descriptions, Spin, Space, Tabs } from 'antd'
import { ArrowLeftOutlined, EditOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getKnowledgePointDetail, getSubjects, getChapters } from '@/api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import EntityAssets from '@/components/EntityAssets'
import PageHeader from '@/components/PageHeader'

const difficultyConfig: Record<string, { color: string; text: string }> = {
  easy: { color: 'green', text: '简单' },
  medium: { color: 'orange', text: '中等' },
  hard: { color: 'red', text: '困难' },
}

const examFreqConfig: Record<string, { color: string; text: string }> = {
  high: { color: 'red', text: '高频' },
  medium: { color: 'orange', text: '中频' },
  low: { color: 'blue', text: '低频' },
  never: { color: 'default', text: '未考' },
}

const KnowledgeDetail = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['knowledgePoint', id],
    queryFn: () => getKnowledgePointDetail(id ?? ''),
    enabled: !!id,
  })

  const { data: subjectsData } = useQuery({
    queryKey: ['subjects'],
    queryFn: getSubjects,
  })

  const point = data?.data
  const subjects = subjectsData?.data || []
  const subject = subjects.find((s) => s.id === point?.subject_id)

  const { data: chaptersData } = useQuery({
    queryKey: ['chapters', point?.subject_id],
    queryFn: () => getChapters(point?.subject_id ?? ''),
    enabled: !!point?.subject_id,
  })

  const chapters = chaptersData?.data || []
  const chapter = chapters.find((c) => c.id === point?.chapter_id)

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  if (!point) {
    return <div>知识点不存在</div>
  }

  const difficulty = difficultyConfig[point.difficulty] || { color: 'default', text: point.difficulty }
  const examFreq = examFreqConfig[point.exam_frequency] || { color: 'default', text: point.exam_frequency }

  return (
    <div className="content-detail-page knowledge-detail-page">
      <PageHeader
        eyebrow="内容资产 / 知识点"
        title={point.title}
        description={`${subject?.name || point.subject_id} · ${chapter?.name || point.chapter_id}`}
        actions={
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/knowledge')}>
              返回列表
            </Button>
            <Button
              type="primary"
              icon={<EditOutlined />}
              onClick={() => navigate(`/admin/knowledge/${id}/edit`)}
            >
              编辑
            </Button>
          </Space>
        }
      />

      <Tabs
        className="content-detail-tabs"
        defaultActiveKey="content"
        items={[
          {
            key: 'content',
            label: '知识点内容',
            children: (
              <Card className="content-detail-card">
                <div style={{ marginBottom: 24 }}>
                  <Space>
                    <Tag color={difficulty.color}>{difficulty.text}</Tag>
                    <Tag color={examFreq.color}>{examFreq.text}</Tag>
                    {point.tags?.map((tag) => (
                      <Tag key={tag}>{tag}</Tag>
                    ))}
                  </Space>
                </div>
                <div
                  className="markdown-content"
                  style={{
                    lineHeight: 1.8,
                    fontSize: 14,
                    color: '#333',
                  }}
                >
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {point.content || '暂无内容'}
                  </ReactMarkdown>
                </div>
              </Card>
            ),
          },
          {
            key: 'info',
            label: '基本信息',
            children: (
              <Card className="content-detail-card">
                <Descriptions bordered column={2}>
                  <Descriptions.Item label="学科">{subject?.name || point.subject_id}</Descriptions.Item>
                  <Descriptions.Item label="章节">{chapter?.name || point.chapter_id}</Descriptions.Item>
                  <Descriptions.Item label="难度">
                    <Tag color={difficulty.color}>{difficulty.text}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="考频">
                    <Tag color={examFreq.color}>{examFreq.text}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="来源">{point.source || '-'}</Descriptions.Item>
                  <Descriptions.Item label="来源页码">{point.source_page || '-'}</Descriptions.Item>
                  <Descriptions.Item label="状态">
                    <Tag color={point.status === 'active' ? 'green' : 'default'}>
                      {point.status === 'active' ? '已发布' : '待审核'}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="创建时间">{point.created_at || '-'}</Descriptions.Item>
                </Descriptions>
              </Card>
            ),
          },
          {
            key: 'keypoints',
            label: '核心要点',
            children: (
              <Card className="content-detail-card">
                {point.key_points && point.key_points.length > 0 ? (
                  <div>
                    {point.key_points.map((kp, idx) => (
                      <div
                        key={idx}
                        style={{
                          padding: '12px 16px',
                          marginBottom: 12,
                          background: '#f5f5f5',
                          borderRadius: 4,
                          borderLeft: '4px solid #1890ff',
                        }}
                      >
                        <Space>
                          <Tag color="blue">{idx + 1}</Tag>
                          <span style={{ fontSize: 14 }}>{kp}</span>
                        </Space>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ color: '#999', textAlign: 'center', padding: 40 }}>
                    暂无核心要点
                  </div>
                )}
              </Card>
            ),
          },
          {
            key: 'assets',
            label: `图片/表格/公式 (${(point as any).assets?.length || 0})`,
            children: (
              <Card className="content-detail-card">
                <EntityAssets assets={(point as any).assets || []} />
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}

export default KnowledgeDetail
