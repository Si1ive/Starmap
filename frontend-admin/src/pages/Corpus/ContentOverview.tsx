import { useQuery } from '@tanstack/react-query'
import { Collapse, Tag, Space, Empty, Spin, Row, Col, Card, Statistic, Table, Typography } from 'antd'
import { getDocumentContentOverview } from '@/api'
import type { ContentOverviewKPBrief, ContentOverviewQuestion } from '@/api/corpus'

const { Paragraph, Text } = Typography

const reviewStatusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'orange', text: '待审核' },
  approved: { color: 'green', text: '已通过' },
  rejected: { color: 'red', text: '已拒绝' },
}

const questionTypeText: Record<string, string> = {
  choice: '选择',
  fill: '填空',
  judge: '判断',
  short_answer: '简答',
  design: '设计',
  analysis: '分析',
}

function ReviewTag({ status }: { status: string }) {
  const cfg = reviewStatusConfig[status] || { color: 'default', text: status }
  return <Tag color={cfg.color}>{cfg.text}</Tag>
}

function KnowledgePointList({ items }: { items: ContentOverviewKPBrief[] }) {
  return (
    <div>
      {items.map((kp) => (
        <div key={kp.id} style={{ padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
          <Space>
            <Text strong>{kp.title}</Text>
            <ReviewTag status={kp.review_status} />
          </Space>
          {kp.summary && (
            <Paragraph type="secondary" style={{ margin: '4px 0 0' }}>{kp.summary}</Paragraph>
          )}
          {!kp.summary && kp.content_preview && (
            <Paragraph type="secondary" style={{ margin: '4px 0 0' }} ellipsis={{ rows: 2 }}>
              {kp.content_preview}
            </Paragraph>
          )}
          {kp.topic_terms?.length > 0 && (
            <Space size={[0, 4]} wrap style={{ marginTop: 4 }}>
              {kp.topic_terms.map((t, i) => <Tag key={i}>{t}</Tag>)}
            </Space>
          )}
          {kp.source_section_path && (
            <div style={{ marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>来源路径：{kp.source_section_path}</Text>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

const ContentOverview = ({ documentId }: { documentId: string }) => {
  const { data, isLoading } = useQuery({
    queryKey: ['contentOverview', documentId],
    queryFn: () => getDocumentContentOverview(documentId),
    enabled: !!documentId,
  })

  if (isLoading) {
    return <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
  }

  const overview = data?.data
  if (!overview) {
    return <Empty description="暂无内容，请先抽取知识点/题目" />
  }

  const { knowledge_chapters, ungrouped_knowledge_points, questions, summary } = overview

  const questionColumns = [
    {
      title: '题号', dataIndex: 'question_no', key: 'question_no', width: 80,
      render: (v: string | null) => v || '-',
    },
    {
      title: '题型', dataIndex: 'type', key: 'type', width: 80,
      render: (v: string) => <Tag>{questionTypeText[v] || v}</Tag>,
    },
    {
      title: '内容', dataIndex: 'content_preview', key: 'content_preview',
      render: (v: string) => <Text style={{ fontSize: 13 }}>{v}</Text>,
    },
    {
      title: '考点', dataIndex: 'primary_chapter_name', key: 'primary_chapter_name', width: 160,
      render: (v: string | null) => v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">未挂考点</Text>,
    },
    {
      title: '年份', dataIndex: 'exam_year', key: 'exam_year', width: 80,
      render: (v: number) => v > 0 ? v : '-',
    },
    {
      title: '状态', dataIndex: 'review_status', key: 'review_status', width: 90,
      render: (s: string) => <ReviewTag status={s} />,
    },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="知识点" value={summary.knowledge_count} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="题目" value={summary.question_count} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="覆盖考点" value={summary.chapter_count} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="未挂考点知识点" value={summary.ungrouped_count} valueStyle={{ color: summary.ungrouped_count > 0 ? '#faad14' : undefined }} /></Card></Col>
      </Row>

      {(knowledge_chapters.length > 0 || ungrouped_knowledge_points.length > 0) && (
        <Card title="知识点（按考点分组）" size="small" style={{ marginBottom: 16 }}>
          <Collapse
            defaultActiveKey={knowledge_chapters.map((c) => c.chapter_id)}
            items={[
              ...knowledge_chapters.map((ch) => ({
                key: ch.chapter_id,
                label: (
                  <Space>
                    {ch.outline_code && <Tag color="geekblue">{ch.outline_code}</Tag>}
                    <Text strong>{ch.chapter_name}</Text>
                    <Text type="secondary">({ch.knowledge_points.length})</Text>
                  </Space>
                ),
                children: (
                  <>
                    {ch.keywords?.length > 0 && (
                      <div style={{ marginBottom: 8 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>考点关键词：</Text>
                        <Space size={[0, 4]} wrap>
                          {ch.keywords.map((k, i) => <Tag key={i} color="cyan">{k}</Tag>)}
                        </Space>
                      </div>
                    )}
                    {ch.exam_guidance && (
                      <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
                        复习指导：{ch.exam_guidance}
                      </Paragraph>
                    )}
                    <KnowledgePointList items={ch.knowledge_points} />
                  </>
                ),
              })),
              ...(ungrouped_knowledge_points.length > 0 ? [{
                key: '__ungrouped__',
                label: (
                  <Space>
                    <Tag color="orange">未挂考点</Tag>
                    <Text type="secondary">({ungrouped_knowledge_points.length})</Text>
                  </Space>
                ),
                children: <KnowledgePointList items={ungrouped_knowledge_points} />,
              }] : []),
            ]}
          />
        </Card>
      )}

      {questions.length > 0 && (
        <Card title="题目（按题号排列）" size="small">
          <Table
            dataSource={questions}
            columns={questionColumns}
            rowKey="id"
            size="small"
            pagination={{ pageSize: 50, showSizeChanger: true }}
            expandable={{
              expandedRowRender: (q: ContentOverviewQuestion) => (
                <div style={{ padding: '4px 12px' }}>
                  <Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 8 }}>{q.content_preview}</Paragraph>
                  {q.options?.length > 0 && (
                    <Space direction="vertical" size={2}>
                      {q.options.map((opt, i) => (
                        <Text key={i}>{opt.key}. {opt.text}</Text>
                      ))}
                    </Space>
                  )}
                  {q.source_section_path && (
                    <div style={{ marginTop: 8 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>来源路径：{q.source_section_path}</Text>
                    </div>
                  )}
                </div>
              ),
            }}
          />
        </Card>
      )}

      {knowledge_chapters.length === 0 && ungrouped_knowledge_points.length === 0 && questions.length === 0 && (
        <Empty description="暂无知识点/题目，请先在上方抽取" />
      )}
    </div>
  )
}

export default ContentOverview
