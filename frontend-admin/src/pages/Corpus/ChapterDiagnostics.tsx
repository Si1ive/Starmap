import { useMemo, useState } from 'react'
import { Alert, Card, Col, Empty, Row, Select, Space, Spin, Statistic, Table, Tag, Typography } from 'antd'
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
  const pages = diagnostics?.pages || []
  const blocks = blockDiagnostics?.blocks || []
  const summary = diagnostics?.summary

  const filteredPages = useMemo(() => {
    if (statusFilter === 'all') {
      return pages
    }
    return pages.filter((page) => page.diagnostic_status === statusFilter)
  }, [pages, statusFilter])

  const pageOptions = Array.from({ length: totalPages || diagnostics?.summary.total_pages || 0 }, (_, i) => ({
    label: `第 ${i + 1} 页`,
    value: i + 1,
  }))

  const pageColumns = [
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
    {
      title: '原生章节',
      key: 'native_section',
      render: (_: unknown, row: ChapterDiagnosticPage) => row.native_section?.title || <Text type="secondary">无覆盖</Text>,
      ellipsis: true,
    },
    {
      title: '抽取最终归属',
      key: 'extraction_mapping',
      render: (_: unknown, row: ChapterDiagnosticPage) => renderMapping(row.extraction_mapping),
    },
    {
      title: '题目/选项信号',
      key: 'signals',
      width: 120,
      render: (_: unknown, row: ChapterDiagnosticPage) => `${row.question_start_count}/${row.option_block_count}`,
    },
    {
      title: '已落库',
      key: 'extracted',
      width: 130,
      render: (_: unknown, row: ChapterDiagnosticPage) => `知识点 ${row.extracted.knowledge_count} / 题目 ${row.extracted.question_count}`,
    },
    {
      title: '诊断',
      key: 'issues',
      render: (_: unknown, row: ChapterDiagnosticPage) => renderIssues(row.issues),
    },
  ]

  const blockColumns = [
    {
      title: '顺序',
      dataIndex: 'order_no',
      key: 'order_no',
      width: 80,
    },
    {
      title: '类型',
      dataIndex: 'block_type',
      key: 'block_type',
      width: 100,
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
    {
      title: '原生章节',
      key: 'native_section',
      render: (_: unknown, row: ChapterDiagnosticBlock) => row.native_section?.title || <Text type="secondary">无覆盖</Text>,
      ellipsis: true,
    },
    {
      title: '抽取最终归属',
      key: 'extraction_mapping',
      render: (_: unknown, row: ChapterDiagnosticBlock) => renderMapping(row.extraction_mapping),
    },
    {
      title: '诊断',
      key: 'issues',
      render: (_: unknown, row: ChapterDiagnosticBlock) => renderIssues(row.issues),
    },
  ]

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

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="该视图用于定位从解析块到章节归属再到实体抽取的断点：映射表稀疏不一定代表页没有归属，但回退归属、拒绝映射和无标题树覆盖都会影响抽取质量。"
      />

      {summary && (
        <Row gutter={16}>
          <Col span={6}>
            <Card size="small">
              <Statistic title="原生章节 / 映射" value={`${summary.total_sections} / ${summary.total_mappings}`} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="异常页" value={summary.pages_warning + summary.pages_error} suffix={`/ ${summary.total_pages}`} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="题目信号" value={summary.question_like_blocks} suffix={`块`} />
            </Card>
          </Col>
          <Col span={6}>
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
        title="页级章节归属"
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
              placeholder="查看块级明细"
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
          dataSource={filteredPages}
          columns={pageColumns}
          pagination={{ pageSize: 20, showSizeChanger: true }}
          onRow={(record) => ({
            onClick: () => setSelectedPage(record.page_no),
          })}
        />
      </Card>

      <Card size="small" title={selectedPage ? `第 ${selectedPage} 页块级归属` : '块级归属'}>
        {!selectedPage ? (
          <Empty description="请选择页码查看块级诊断" />
        ) : blockQuery.isLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin tip="加载块级诊断..." />
          </div>
        ) : (
          <Table
            size="small"
            rowKey="id"
            dataSource={blocks}
            columns={blockColumns}
            pagination={{ pageSize: 20, showSizeChanger: true }}
          />
        )}
      </Card>
    </Space>
  )
}

export default ChapterDiagnostics
