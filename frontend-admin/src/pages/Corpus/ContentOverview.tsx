import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  Collapse,
  Empty,
  message,
  Modal,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { FormOutlined, ReloadOutlined } from '@ant-design/icons'
import { getDocumentContentOverview, reextractDocumentEntity } from '@/api'
import type {
  ContentOverview,
  ContentOverviewKPBrief,
  ContentOverviewQuestion,
  ContentQualityGate,
  EntityExtractionRun,
  ReextractEntityType,
} from '@/api/corpus'

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

function ChapterNameTag({ name }: { name: string }) {
  return (
    <Tooltip title={name} placement="topLeft">
      <Tag
        color="blue"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          maxWidth: '100%',
          marginInlineEnd: 0,
        }}
      >
        <span
          style={{
            minWidth: 0,
            maxWidth: '100%',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {name}
        </span>
      </Tag>
    </Tooltip>
  )
}

function ReextractionTag({ run }: { run?: EntityExtractionRun | null }) {
  if (!run) return null
  if (run.status === 'running') {
    return <Tag color="processing">重新提取中</Tag>
  }
  if (run.status === 'success') {
    return <Tag color="green">已重新提取</Tag>
  }
  return <Tag color="red" title={run.error_detail || '重新提取失败'}>重提取失败</Tag>
}

function collectEntityRuns(overview?: ContentOverview): EntityExtractionRun[] {
  if (!overview) return []
  return [
    ...overview.knowledge_chapters.flatMap((chapter) => (
      chapter.knowledge_points.map((item) => item.reextraction)
    )),
    ...overview.ungrouped_knowledge_points.map((item) => item.reextraction),
    ...overview.questions.map((item) => item.reextraction),
  ].filter((run): run is EntityExtractionRun => !!run)
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
  const issues = gate.issues || []
  const issueCheckKeys = new Set(issues.map((issue) => issue.check_key))
  const attentionChecks = gate.checks.filter((check) => (
    check.status !== 'pass' && check.status !== 'pending'
      && !issueCheckKeys.has(check.key)
  ))
  const conclusion = {
    passed: '当前未发现阻断或待核验问题，可以入库。',
    warning: '当前无阻断问题，入库前建议核验以下内容。',
    blocked: '当前不建议入库，请先处理下方标记为“阻断”的问题。',
    running: '抽取任务仍在执行，完成后会自动更新质量结论。',
    failed: '最新抽取任务失败，请查看下方原因后重新执行。',
    not_run: '尚未执行实体抽取，暂无可评估的入库内容。',
  }[gate.status]

  return (
    <Alert
      className="workspace-callout quality-gate-summary"
      type={config.alertType}
      showIcon
      style={{ marginBottom: 16 }}
      message={(
        <Space wrap>
          <Text strong>入库质量</Text>
          <Tag color={config.color}>{gate.label}</Tag>
          <Text type="secondary">{gate.score} 分</Text>
        </Space>
      )}
      description={(
        <div>
          <Text>{conclusion}</Text>
          {(issues.length > 0 || attentionChecks.length > 0) && (
            <div style={{ marginTop: 8, maxHeight: 280, overflowY: 'auto' }}>
              {issues.map((issue) => (
                <QualityIssueRow
                  key={issue.key}
                  level={issue.severity}
                  label={issue.entity_label}
                  message={issue.message}
                />
              ))}
              {attentionChecks.map((check) => (
                <QualityIssueRow
                  key={check.key}
                  level={
                    check.status === 'fail'
                      ? 'fail'
                      : check.status === 'running'
                        ? 'running'
                        : 'warning'
                  }
                  label={check.label}
                  message={check.message}
                />
              ))}
            </div>
          )}
        </div>
      )}
    />
  )
}

function QualityIssueRow({
  level,
  label,
  message: issueMessage,
}: {
  level: 'fail' | 'warning' | 'running'
  label: string
  message: string
}) {
  const levelConfig = {
    fail: { color: 'red', text: '阻断' },
    warning: { color: 'gold', text: '待核验' },
    running: { color: 'blue', text: '进行中' },
  }[level]

  return (
    <div
      className="quality-issue-row"
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 8,
        padding: '7px 0',
        borderTop: '1px solid rgba(5, 5, 5, 0.08)',
      }}
    >
      <Tag
        color={levelConfig.color}
        style={{ minWidth: 52, marginInlineEnd: 0, textAlign: 'center' }}
      >
        {levelConfig.text}
      </Tag>
      <div style={{ minWidth: 0, lineHeight: '22px' }}>
        <Text strong style={{ marginRight: 8 }}>{label}</Text>
        <Text>{issueMessage}</Text>
      </div>
    </div>
  )
}

function KnowledgePointList({
  items,
  taskBusy,
  pendingKey,
  onReextract,
}: {
  items: ContentOverviewKPBrief[]
  taskBusy: boolean
  pendingKey: string | null
  onReextract: (item: ContentOverviewKPBrief) => void
}) {
  return (
    <div className="content-overview__knowledge-list">
      {items.map((kp) => (
        <div key={kp.id} className="content-overview__knowledge-item">
          <div className="content-overview__knowledge-row">
            <Space size={[4, 4]} wrap>
              <Text strong>{kp.title}</Text>
              <ReviewTag status={kp.review_status} />
              <ReextractionTag run={kp.reextraction} />
            </Space>
            <Tooltip title="仅使用该知识点的来源内容重新提取">
              <Button
                aria-label={`重新提取知识点：${kp.title}`}
                icon={<ReloadOutlined />}
                size="small"
                loading={kp.reextraction?.status === 'running' || pendingKey === `knowledge_point:${kp.id}`}
                disabled={
                  taskBusy
                  && kp.reextraction?.status !== 'running'
                  && pendingKey !== `knowledge_point:${kp.id}`
                }
                onClick={() => onReextract(kp)}
              >
                重新提取
              </Button>
            </Tooltip>
          </div>
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

const ContentOverview = ({
  documentId,
  documentExtracting = false,
}: {
  documentId: string
  documentExtracting?: boolean
}) => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['contentOverview', documentId],
    queryFn: () => getDocumentContentOverview(documentId),
    enabled: !!documentId,
    refetchInterval: (response) => (
      collectEntityRuns(response?.data).some((run) => run.status === 'running')
        ? 2000
        : false
    ),
  })

  const reextractMutation = useMutation({
    mutationFn: ({
      entityType,
      entityId,
    }: {
      entityType: ReextractEntityType
      entityId: string
      label: string
    }) => reextractDocumentEntity(documentId, entityType, entityId),
    onSuccess: (response) => {
      message.success(response.message || '单项重新提取任务已启动')
      queryClient.invalidateQueries({ queryKey: ['contentOverview', documentId] })
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail
      message.error(typeof detail === 'string' ? detail : '单项重新提取失败')
      queryClient.invalidateQueries({ queryKey: ['contentOverview', documentId] })
    },
  })

  const overview = data?.data
  const entityRuns = collectEntityRuns(overview)
  const hasRunningEntityTask = entityRuns.some((run) => run.status === 'running')
  const pendingKey = reextractMutation.isPending
    ? `${reextractMutation.variables?.entityType}:${reextractMutation.variables?.entityId}`
    : null
  const taskBusy = documentExtracting || hasRunningEntityTask || reextractMutation.isPending

  if (isLoading) {
    return <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
  }

  if (!overview) {
    return <Empty description="尚未抽取 — 内容总览展示的是抽取产物，请先点击上方「抽取知识点/题目」" />
  }

  const { knowledge_chapters, ungrouped_knowledge_points, questions, summary, quality_gate } = overview
  const requestReextraction = (
    entityType: ReextractEntityType,
    entityId: string,
    label: string,
  ) => {
    Modal.confirm({
      title: `确认重新提取${entityType === 'question' ? '题目' : '知识点'}`,
      content: `只会重新读取“${label}”的来源内容并覆盖该项抽取结构，不会重跑整份文档。`,
      okText: '重新提取',
      onOk: () => reextractMutation.mutate({ entityType, entityId, label }),
    })
  }

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
      align: 'center' as const,
      onCell: () => ({ style: { overflow: 'hidden' } }),
      render: (v: string | null, row: ContentOverviewQuestion) =>
        v
          ? <ChapterNameTag name={v} />
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
      render: (s: string, row: ContentOverviewQuestion) => (
        <Space size={[0, 4]} wrap>
          <ReviewTag status={s} />
          <ReextractionTag run={row.reextraction} />
        </Space>
      ),
    },
    {
      title: '操作', key: 'actions', width: 196, fixed: 'right' as const,
      render: (_: unknown, row: ContentOverviewQuestion) => {
        const key = `question:${row.id}`
        const isRunning = row.reextraction?.status === 'running'
        return (
          <Space size={6}>
            <Tooltip title="在题目管理中定位并人工处理">
              <Button
                aria-label={`管理题目：${row.question_no || row.id}`}
                icon={<FormOutlined />}
                size="small"
                onClick={() => navigate(
                  `/admin/questions?question_id=${encodeURIComponent(row.id)}`
                )}
              >
                管理
              </Button>
            </Tooltip>
            <Tooltip title="仅使用本题及相邻两题的来源内容重新提取">
              <Button
                aria-label={`重新提取题目：${row.question_no || row.id}`}
                icon={<ReloadOutlined />}
                size="small"
                loading={isRunning || pendingKey === key}
                disabled={taskBusy && !isRunning && pendingKey !== key}
                onClick={() => requestReextraction(
                  'question',
                  row.id,
                  row.question_no ? `第 ${row.question_no} 题` : row.content_preview.slice(0, 24),
                )}
              >
                重新提取
              </Button>
            </Tooltip>
          </Space>
        )
      },
    },
  ]

  return (
    <div className="content-overview">
      <QualityGateSummary gate={quality_gate} />

      <div className="content-overview__metrics">
        <Card className="content-overview__metric" size="small"><Statistic title="知识点" value={summary.knowledge_count} /></Card>
        <Card className="content-overview__metric" size="small"><Statistic title="题目" value={summary.question_count} /></Card>
        <Card className="content-overview__metric" size="small"><Statistic title="覆盖考点" value={summary.chapter_count} /></Card>
        <Card className="content-overview__metric" size="small"><Statistic title="未挂考点知识点" value={summary.ungrouped_count} valueStyle={{ color: summary.ungrouped_count > 0 ? '#faad14' : undefined }} /></Card>
        <Card className="content-overview__metric" size="small"><Statistic title="未归属题目" value={summary.unassigned_question_count} valueStyle={{ color: summary.unassigned_question_count > 0 ? '#fa541c' : undefined }} /></Card>
      </div>

      {(knowledge_chapters.length > 0 || ungrouped_knowledge_points.length > 0) && (
        <Card className="workspace-panel content-overview__knowledge" title="知识点（按考点分组）" size="small" style={{ marginBottom: 16 }}>
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
                    <KnowledgePointList
                      items={ch.knowledge_points}
                      taskBusy={taskBusy}
                      pendingKey={pendingKey}
                      onReextract={(item) => requestReextraction('knowledge_point', item.id, item.title)}
                    />
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
                children: (
                  <KnowledgePointList
                    items={ungrouped_knowledge_points}
                    taskBusy={taskBusy}
                    pendingKey={pendingKey}
                    onReextract={(item) => requestReextraction('knowledge_point', item.id, item.title)}
                  />
                ),
              }] : []),
            ]}
          />
        </Card>
      )}

      {questions.length > 0 && (
        <Card className="workspace-panel content-overview__questions" title="题目（按题号排列）" size="small">
          <Table
            dataSource={questions}
            columns={questionColumns}
            rowKey="id"
            size="small"
            scroll={{ x: 1100 }}
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
