import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Tag, Space, Descriptions, message, Spin, Empty, Select, Modal, Alert, Tabs } from 'antd'
import { ArrowLeftOutlined, ExperimentOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getDocumentDetail,
  extractDocumentEntities,
  getDocumentEntityExtractionStatus,
  getSubjects,
  getDocumentContentOverview,
} from '@/api'
import PageAnalysis from './PageAnalysis'
import ContentOverview from './ContentOverview'

const EXAM_DOC_TYPES = new Set(['past_exam', 'mock_exam'])

const docTypeText: Record<string, string> = {
  textbook: '教材',
  past_exam: '真题',
  mock_exam: '模拟卷',
  notes: '笔记',
  other: '其他',
}

const DocumentDetailPage = () => {
  const { id } = useParams<{ id: string }>()
  const documentId = id ?? ''
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selectedSubject, setSelectedSubject] = useState('')

  const { data: docData, isLoading } = useQuery({
    queryKey: ['document', documentId],
    queryFn: () => getDocumentDetail(documentId),
    enabled: !!documentId,
  })

  const { data: subjectsData } = useQuery({
    queryKey: ['subjects'],
    queryFn: getSubjects,
  })

  const { data: overviewData } = useQuery({
    queryKey: ['contentOverview', documentId],
    queryFn: () => getDocumentContentOverview(documentId),
    enabled: !!documentId,
  })

  const { data: extractionStatusData } = useQuery({
    queryKey: ['entityExtractionStatus', documentId],
    queryFn: () => getDocumentEntityExtractionStatus(documentId),
    enabled: !!documentId,
    refetchInterval: (queryData) =>
      queryData?.data?.status === 'running' ? 2000 : false,
  })

  const document = docData?.data
  const subjects = subjectsData?.data || []
  const isExamDoc = !!document && EXAM_DOC_TYPES.has(document.doc_type || '')
  const extractionRun = extractionStatusData?.data

  const summary = overviewData?.data?.summary
  const extractedCount = (summary?.knowledge_count ?? 0) + (summary?.question_count ?? 0)
  const hasExtracted = extractedCount > 0
  const isExtracting = extractionRun?.status === 'running'
  const observedRunningId = useRef<string | null>(null)

  const extractEntitiesMut = useMutation({
    mutationFn: () => extractDocumentEntities(documentId, selectedSubject || document?.subject_id),
    onSuccess: (res) => {
      queryClient.setQueryData(['entityExtractionStatus', documentId], res)
      observedRunningId.current = res.data?.id || null
      message.success(res.message || '抽取任务已启动')
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      message.error(typeof detail === 'string' ? detail : '抽取失败')
    },
  })

  useEffect(() => {
    if (!extractionRun) return
    if (extractionRun.status === 'running') {
      observedRunningId.current = extractionRun.id
      return
    }
    if (observedRunningId.current !== extractionRun.id) return

    observedRunningId.current = null
    if (extractionRun.status === 'success') {
      const indexing = extractionRun.result?.indexing
      const segmentCount =
        (indexing?.knowledge_segments?.segments_count ?? 0)
        + (indexing?.question_segments?.segments_count ?? 0)
      message.success(
        `抽取并索引完成：知识点 ${extractionRun.knowledge_count ?? 0}，题目 ${extractionRun.question_count ?? 0}，检索单元 ${segmentCount}`
      )
      queryClient.invalidateQueries({ queryKey: ['document', documentId] })
      queryClient.invalidateQueries({ queryKey: ['contentOverview', documentId] })
    } else {
      message.error(extractionRun.error_detail || '抽取失败')
    }
  }, [extractionRun, documentId, queryClient])

  if (isLoading) {
    return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  }

  if (!document) {
    return <Empty description="文档不存在" />
  }

  const subjectOptions = subjects.map((s: any) => ({ label: s.name, value: s.id }))

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/corpus')} style={{ marginBottom: 16 }}>
        返回列表
      </Button>

      <Card style={{ marginBottom: 16 }}>
        <Descriptions title="第一步 · 解析产物（文档信息）" column={2}>
          <Descriptions.Item label="文件名">{document.file_name || document.title || '-'}</Descriptions.Item>
          <Descriptions.Item label="文档类型">
            <Tag color={isExamDoc ? 'volcano' : 'blue'}>{docTypeText[document.doc_type || ''] || document.doc_type || '-'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="状态">{document.status}</Descriptions.Item>
          <Descriptions.Item label="页数">{document.page_count || document.pages?.length || '-'}</Descriptions.Item>
          <Descriptions.Item label="Block 数">{document.block_count || document.blocks?.length || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {document.created_at ? new Date(document.created_at).toLocaleString('zh-CN') : '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        style={{ marginBottom: 16 }}
        title={
          <Space>
            <span>第二步 · 抽取知识点/题目</span>
            {isExtracting ? (
              <Tag color="processing">抽取中</Tag>
            ) : hasExtracted ? (
              <Tag color="green">已抽取 {extractedCount} 项</Tag>
            ) : (
              <Tag color="default">尚未抽取</Tag>
            )}
            {extractionRun?.status === 'failed' && <Tag color="red">最近抽取失败</Tag>}
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="解析与抽取是两个独立步骤"
          description="上一步「解析」只把 PDF 拆成文字/图片/表格等版面块；这一步「抽取」才用 LLM 把版面块理解成知识点和题目，并挂到学科+标准章节上。重新解析会清空本文档已抽取的实体，需要重新点此抽取。"
        />
        <Space>
          <Select
            placeholder={isExamDoc ? '选择兜底学科（必选）' : '全部学科（自动识别）'}
            style={{ width: 220 }}
            value={selectedSubject || (isExamDoc ? document.subject_id : undefined) || undefined}
            onChange={setSelectedSubject}
            allowClear
            options={subjectOptions}
            disabled={isExtracting || extractEntitiesMut.isPending}
          />
          <Button
            type="primary"
            icon={<ExperimentOutlined />}
            loading={isExtracting || extractEntitiesMut.isPending}
            onClick={() => Modal.confirm({
              title: hasExtracted ? '确认重新抽取' : '确认抽取',
              content: hasExtracted
                ? '本文档已有抽取结果，重新抽取会先清空旧的知识点/题目再重建，确认继续？'
                : (isExamDoc
                  ? '将从文档中抽取题目并挂到指定学科+标准章节，确认继续？'
                  : '将从文档中抽取知识点和题目并挂到标准章节，确认继续？'),
              onOk: () => extractEntitiesMut.mutate(),
            })}
          >
            {isExtracting
              ? '抽取中'
              : hasExtracted
                ? '重新抽取'
                : (isExamDoc ? '抽取题目' : '抽取知识点/题目')}
          </Button>
        </Space>
      </Card>

      <Card>
        <Tabs
          defaultActiveKey="content-overview"
          items={[
            {
              key: 'content-overview',
              label: '内容总览（抽取产物）',
              children: (
                <ContentOverview
                  documentId={documentId}
                  documentExtracting={isExtracting}
                />
              ),
            },
            {
              key: 'page-analysis',
              label: '页级对比（解析产物）',
              children: (
                <PageAnalysis
                  documentId={documentId}
                  totalPages={document?.page_count || document?.pages?.length || 0}
                />
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}

export default DocumentDetailPage
