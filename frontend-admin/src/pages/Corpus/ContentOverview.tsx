import { useQuery } from '@tanstack/react-query'
import { Alert, Collapse, Tag, Space, Empty, Spin, Row, Col, Card, Statistic, Table, Typography } from 'antd'
import { getDocumentContentOverview } from '@/api'
import type { ContentOverviewKPBrief, ContentOverviewQuestion, ContentQualityGate } from '@/api/corpus'

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

const originalIssueText: Record<string, string> = {
  missing_all: '原问题：选项全部缺失',
  missing_start: '原问题：开头选项缺失',
  missing_middle: '原问题：中间选项缺失',
  missing_end: '原问题：末尾选项缺失',
  too_few: '原问题：选项不足',
}

const qualityStatusConfig: Record<ContentQualityGate['status'], {
  alertType: 'success' | 'warning' | 'error' | 'info'
  color: string
}> = {
  passed: { alertType: 'success', color: 'green' },
  warning: { alertType: 'warning', color: 'gold' },
  blocked: { alertType: 'error', color: 'red' },
  running: { alertType: 'info', color: 'blue' },
  failed: { alertType: 'error', color: 'red' },
  not_run: { alertType: 'info', color: 'default' },
}

function ReviewTag({ status }: { status: string }) {
  const cfg = reviewStatusConfig[status] || { color: 'default', text: status }
  return <Tag color={cfg.color}>{cfg.text}</Tag>
}

// 把 extraction_meta 翻译成人能看懂的质量警示标签。无警示时返回"正常"绿标。
function QualityBadges({ meta }: { meta?: Record<string, any> | null }) {
  if (!meta) return <Text type="secondary">-</Text>
  const badges: Array<{ color: string; text: string; title: string }> = []
  if (meta.fixed_by_llm) {
    badges.push({ color: 'cyan', text: 'LLM 已修复', title: '该题已由 LLM 修复，原问题仍保留在后续标签中' })
  }
  const originalIssueTypes = Array.from(new Set(
    (meta.original_issues || [])
      .map((issue: { issue_type?: string }) => issue?.issue_type)
      .filter(Boolean)
  )) as string[]
  originalIssueTypes.forEach((issueType) => {
    badges.push({
      color: 'gold',
      text: originalIssueText[issueType] || `原问题：${issueType}`,
      title: '修复前检测到的问题',
    })
  })
  if (meta.suspected_truncated_options) {
    badges.push({ color: 'red', text: '选项截断', title: '选项文本疑似被 MinerU 截断（过短）' })
  }
  if (meta.few_options) {
    badges.push({ color: 'orange', text: '选项不足', title: '选择题选项少于 4 个，可能漏选项（常见 D 丢失）' })
  }
  if (meta.missing_question_no) {
    badges.push({ color: 'gold', text: '无题号', title: '未识别出题号，可能是题号被吞或非标准题目' })
  }
  if (meta.group_source === 'merged') {
    badges.push({ color: 'blue', text: '多块合并', title: `由 ${meta.block_count ?? '多'} 个 block 合并而成` })
  }
  if (badges.length === 0) {
    return <Tag color="green">正常</Tag>
  }
  return (
    <Space size={[0, 4]} wrap>
      {badges.map((b, i) => (
        <Tag key={i} color={b.color} title={b.title}>{b.text}</Tag>
      ))}
    </Space>
  )
}

function QualityGateSummary({ gate }: { gate: ContentQualityGate }) {
  const config = qualityStatusConfig[gate.status]
  const attentionChecks = gate.checks.filter((check) => (
    check.status !== 'pass' && check.status !== 'pending'
  ))
  const metrics = gate.metrics

  return (
    <Alert
      type={config.alertType}
      showIcon
      style={{ marginBottom: 16 }}
      message={(
        <Space wrap>
          <Text strong>入库质量门禁</Text>
          <Tag color={config.color}>{gate.label}</Tag>
          <Text>{gate.score} 分</Text>
        </Space>
      )}
      description={(
        <Space direction="vertical" size={8}>
          <Text>{gate.summary}</Text>
          {attentionChecks.length > 0 && (
            <Space size={[0, 6]} wrap>
              {attentionChecks.map((check) => (
                <Tag
                  key={check.key}
                  color={check.status === 'fail' ? 'red' : check.status === 'running' ? 'blue' : 'gold'}
                  title={check.message}
                >
                  {check.label}：{check.message}
                </Tag>
              ))}
            </Space>
          )}
          <Space size={[0, 6]} wrap>
            {metrics.llm_repaired_question_count > 0 && (
              <Tag color="cyan">LLM 修复 {metrics.llm_repaired_question_count} 题</Tag>
            )}
            {metrics.recovered_option_count > 0 && (
              <Tag color="blue">原文恢复选项 {metrics.recovered_option_count} 个</Tag>
            )}
            {metrics.ai_generated_option_count > 0 && (
              <Tag color="gold">AI 生成选项 {metrics.ai_generated_option_count} 个</Tag>
            )}
            {metrics.initial_issue_count > 0 && (
              <Tag>问题数 {metrics.initial_issue_count} → {metrics.final_issue_count}</Tag>
            )}
          </Space>
        </Space>
      )}
    />
  )
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
    return <Empty description="尚未抽取 — 内容总览展示的是抽取产物，请先点击上方「抽取知识点/题目」" />
  }

  const { knowledge_chapters, ungrouped_knowledge_points, questions, summary, quality_gate } = overview

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
      render: (v: string | null, row: ContentOverviewQuestion) =>
        v
          ? <Tag color="blue">{v}</Tag>
          : row.is_unassigned
            ? <Tag color="volcano" title="组题成功但未挂到大纲考点，待人工指认">未归属</Tag>
            : <Text type="secondary">未挂考点</Text>,
    },
    {
      title: '抽取质量', key: 'quality', width: 160,
      render: (_: unknown, row: ContentOverviewQuestion) => <QualityBadges meta={row.extraction_meta} />,
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
      <QualityGateSummary gate={quality_gate} />

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={5}><Card size="small"><Statistic title="知识点" value={summary.knowledge_count} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="题目" value={summary.question_count} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="覆盖考点" value={summary.chapter_count} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="未挂考点知识点" value={summary.ungrouped_count} valueStyle={{ color: summary.ungrouped_count > 0 ? '#faad14' : undefined }} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="未归属题目" value={summary.unassigned_question_count} valueStyle={{ color: summary.unassigned_question_count > 0 ? '#fa541c' : undefined }} /></Card></Col>
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
                        <Space key={i} size={6} align="start">
                          <Text>{opt.key || opt.label}. {opt.text}</Text>
                          {opt.source === 'extracted' && <Tag color="blue">原文恢复</Tag>}
                          {opt.source === 'ai_generated' && <Tag color="gold">AI 生成</Tag>}
                        </Space>
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
        <Empty description="尚未抽取或抽取结果为空 — 请点击上方「抽取知识点/题目」" />
      )}
    </div>
  )
}

export default ContentOverview
