import { useMemo, useState } from 'react'
import { Alert, Card, Col, Empty, Row, Select, Space, Spin, Statistic, Table, Tag, Tooltip, Typography } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getDocumentChapterDiagnostics } from '@/api'
import type {
  ChapterDiagnosticBlock,
  ChapterDiagnosticMapping,
  ChapterDiagnosticPage,
  ChapterDiagnosticStatus,
} from '@/types'

const { Text } = Typography

interface ChapterDiagnosticsProps {
  documentId: string
  totalPages: number
}

const statusConfig: Record<ChapterDiagnosticStatus, { color: string; text: string }> = {
  ok: { color: 'green', text: '正常' },
  warning: { color: 'orange', text: '需关注' },
  error: { color: 'red', text: '阻断' },
}

const sourceText: Record<string, string> = {
  native_section: '原生章节',
  section_range: '章节范围',
  previous_page: '前页回退',
  next_page: '后页回退',
}

function renderStatus(status: ChapterDiagnosticStatus) {
  const cfg = statusConfig[status] || statusConfig.warning
  return <Tag color={cfg.color}>{cfg.text}</Tag>
}

function renderMapping(mapping?: ChapterDiagnosticMapping | null) {
  if (!mapping) {
    return <Text type="secondary">未解析</Text>
  }
  const isFallback = mapping.source === 'previous_page' || mapping.source === 'next_page'
  return (
    <Space direction="vertical" size={0}>
      <Text>{mapping.canonical_chapter_name}</Text>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {mapping.subject_name} · {sourceText[mapping.source] || mapping.source}
        {isFallback ? ` ${mapping.fallback_distance}页` : ''}
      </Text>
    </Space>
  )
}

function renderIssues(issues: Array<{ message: string }>) {
  if (!issues.length) {
    return <Text type="secondary">-</Text>
  }
  return (
    <Space direction="vertical" size={0}>
      {issues.map((issue, index) => (
        <Text key={`${issue.message}-${index}`} type="secondary" style={{ fontSize: 12 }}>
          {issue.message}
        </Text>
      ))}
    </Space>
  )
}

const ChapterDiagnostics = ({ documentId, totalPages }: ChapterDiagnosticsProps) => {
  const [selectedPage, setSelectedPage] = useState<number | undefined>()
  const [statusFilter, setStatusFilter] = useState<ChapterDiagnosticStatus | 'all'>('all')

  const overviewQuery = useQuery({
    queryKey: ['chapterDiagnostics', documentId, 'overview'],
    queryFn: () => getDocumentChapterDiagnostics(documentId, { include_blocks: false }),
    enabled: !!documentId,
  })

  const blockQuery = useQuery({
    queryKey: ['chapterDiagnostics', documentId, 'blocks', selectedPage],
    queryFn: () => getDocumentChapterDiagnostics(
      documentId,
      selectedPage ? { page_no: selectedPage, include_blocks: true } : { include_blocks: false },
    ),
    enabled: !!documentId && !!selectedPage,
  })

  const diagnostics = overviewQuery.data?.data
  const blockDiagnostics = blockQuery.data?.data
  const allPages = useMemo(() => diagnostics?.pages ?? [], [diagnostics?.pages])
  const blocks = blockDiagnostics?.blocks || []
  const summary = diagnostics?.summary
  const isExam = !!diagnostics?.is_exam_doc

  const visiblePages = useMemo(() => {
    let result = allPages
    if (selectedPage) {
      result = result.filter((page) => page.page_no === selectedPage)
    }
    if (statusFilter !== 'all') {
      result = result.filter((page) => page.diagnostic_status === statusFilter)
    }
    return result
  }, [allPages, selectedPage, statusFilter])

  const pageOptions = Array.from({ length: totalPages || diagnostics?.summary.total_pages || 0 }, (_, i) => ({
    label: `第 ${i + 1} 页`,
    value: i + 1,
  }))

  const pageColumns: any[] = [
    {
      title: '页码',
      dataIndex: 'page_no',
      key: 'page_no',
      width: 90,
      render: (value: number) => <Text strong>第 {value} 页</Text>,
    },
    {
      title: '状态',
      dataIndex: 'diagnostic_status',
      key: 'diagnostic_status',
      width: 90,
      render: renderStatus,
    },
  ]
  if (!isExam) {
    pageColumns.push({
      title: (
        <Tooltip title="文档自身识别出的章节标题，比如《高等数学》第三章">
          原生章节 <InfoCircleOutlined style={{ color: '#999' }} />
        </Tooltip>
      ),
      key: 'native_section',
      render: (_: unknown, row: ChapterDiagnosticPage) => row.native_section?.title || <Text type="secondary">无覆盖</Text>,
      ellipsis: true,
    })
  }
  pageColumns.push({
    title: (
      <Tooltip title="抽取知识点/题目时实际写入数据库的标准章节归属（含相邻页回退）">
        实际归属 <InfoCircleOutlined style={{ color: '#999' }} />
      </Tooltip>
    ),
    key: 'extraction_mapping',
    render: (_: unknown, row: ChapterDiagnosticPage) => renderMapping(row.extraction_mapping),
  })
  pageColumns.push({
    title: (
      <Tooltip title="该页已落库的知识点/题目数量（与下方信号不一定 1:1，因为一个题目可能跨多个块）">
        已落库 <InfoCircleOutlined style={{ color: '#999' }} />
      </Tooltip>
    ),
    key: 'extracted',
    width: 130,
    render: (_: unknown, row: ChapterDiagnosticPage) => `知识点 ${row.extracted.knowledge_count} / 题目 ${row.extracted.question_count}`,
  })
  pageColumns.push({
    title: '诊断',
    key: 'issues',
    render: (_: unknown, row: ChapterDiagnosticPage) => renderIssues(row.issues),
  })

  const blockColumns: any[] = [
    {
      title: '顺序',
      dataIndex: 'order_no',
      key: 'order_no',
      width: 70,
    },
    {
      title: '类型',
      dataIndex: 'block_type',
      key: 'block_type',
      width: 90,
      render: (value: string) => <Tag color="blue">{value}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'diagnostic_status',
      key: 'diagnostic_status',
      width: 90,
      render: renderStatus,
    },
    {
      title: '内容',
      dataIndex: 'text_excerpt',
      key: 'text_excerpt',
      ellipsis: true,
      render: (value: string, row: ChapterDiagnosticBlock) => (
        <Space direction="vertical" size={0}>
          <Text>{value || '-'}</Text>
          <Space size={4}>
            {row.signals.looks_like_question_start && <Tag color="purple">题目起点</Tag>}
            {row.signals.looks_like_option && <Tag color="cyan">选项</Tag>}
            {row.signals.looks_like_heading && <Tag>标题块</Tag>}
          </Space>
        </Space>
      ),
    },
  ]
  if (!isExam) {
    blockColumns.push({
      title: '原生章节',
      key: 'native_section',
      render: (_: unknown, row: ChapterDiagnosticBlock) => row.native_section?.title || <Text type="secondary">无覆盖</Text>,
      ellipsis: true,
    })
  }
  blockColumns.push({
    title: '实际归属',
    key: 'extraction_mapping',
    render: (_: unknown, row: ChapterDiagnosticBlock) => renderMapping(row.extraction_mapping),
  })
  blockColumns.push({
    title: '诊断',
    key: 'issues',
    render: (_: unknown, row: ChapterDiagnosticBlock) => renderIssues(row.issues),
  })

  if (overviewQuery.isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" tip="加载章节归属诊断..." />
      </div>
    )
  }

  if (!diagnostics) {
    return <Empty description="暂无诊断数据" />
  }

  const expandable = {
    expandedRowRender: (record: ChapterDiagnosticPage) => {
      if (record.page_no !== selectedPage) {
        return <Text type="secondary">点击行展开后会加载该页的块级明细</Text>
      }
      if (blockQuery.isLoading) {
        return <Spin tip="加载块级诊断..." />
      }
      if (!blocks.length) {
        return <Empty description="该页无块" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      }
      return (
        <Table
          size="small"
          rowKey="id"
          dataSource={blocks}
          columns={blockColumns}
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
        />
      )
    },
    expandedRowKeys: selectedPage ? [selectedPage] : [],
    onExpand: (expanded: boolean, record: ChapterDiagnosticPage) => {
      setSelectedPage(expanded ? record.page_no : undefined)
    },
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message={
          isExam
            ? '试卷类文档不构建原生标题树，题目直接挂到学科+标准章节。本视图展示每页题目的实际归属和已落库情况。'
            : '本视图展示从「原生章节」（文档自带标题）到「实际归属」（最终入库的标准章节）的链路。回退归属和未映射都会影响抽取质量。'
        }
      />

      {summary && (
        <Row gutter={16}>
          {!isExam && (
            <Col span={6}>
              <Card size="small">
                <Statistic title="原生章节 / 映射" value={`${summary.total_sections} / ${summary.total_mappings}`} />
              </Card>
            </Col>
          )}
          <Col span={isExam ? 8 : 6}>
            <Card size="small">
              <Statistic title="异常页" value={summary.pages_warning + summary.pages_error} suffix={`/ ${summary.total_pages}`} />
            </Card>
          </Col>
          <Col span={isExam ? 8 : 6}>
            <Card size="small">
              <Statistic title="题目信号块" value={summary.question_like_blocks} suffix="块" />
            </Card>
          </Col>
          <Col span={isExam ? 8 : 6}>
            <Card size="small">
              <Statistic
                title="已抽取"
                value={`${summary.extracted_knowledge_count} / ${summary.extracted_question_count}`}
                suffix="知/题"
              />
            </Card>
          </Col>
        </Row>
      )}

      <Card
        size="small"
        title="页级章节归属（点击行查看该页块级明细）"
        extra={
          <Space>
            <Select
              value={statusFilter}
              style={{ width: 120 }}
              onChange={setStatusFilter}
              options={[
                { label: '全部状态', value: 'all' },
                { label: '正常', value: 'ok' },
                { label: '需关注', value: 'warning' },
                { label: '阻断', value: 'error' },
              ]}
            />
            <Select
              allowClear
              placeholder="跳到页码"
              value={selectedPage}
              style={{ width: 150 }}
              onChange={setSelectedPage}
              options={pageOptions}
            />
          </Space>
        }
      >
        <Table
          size="small"
          rowKey="page_no"
          dataSource={visiblePages}
          columns={pageColumns}
          expandable={expandable}
          pagination={{ pageSize: 20, showSizeChanger: true }}
        />
      </Card>
    </Space>
  )
}

export default ChapterDiagnostics
