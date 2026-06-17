import { useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Tree, Table, Tag, Space, Descriptions, message, Spin, Empty, Select, Modal, Alert, Tooltip, Tabs, Statistic, Row, Col } from 'antd'
import { ArrowLeftOutlined, ApartmentOutlined, NodeIndexOutlined, ExperimentOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getDocumentDetail, getDocumentSections, getSectionMappings, extractDocumentSections, mapDocumentChapters, extractDocumentEntities, getSubjects } from '@/api'
import type { DataNode } from 'antd/es/tree'
import PageAnalysis from './PageAnalysis'
import ChapterDiagnostics from './ChapterDiagnostics'

const EXAM_DOC_TYPES = new Set(['past_exam', 'mock_exam'])

const docTypeText: Record<string, string> = {
  textbook: '教材',
  past_exam: '真题',
  mock_exam: '模拟卷',
  notes: '笔记',
  other: '其他',
}

const reviewStatusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'orange', text: '待审核' },
  approved: { color: 'green', text: '已通过' },
  rejected: { color: 'red', text: '已拒绝' },
}

function buildTreeData(sections: any[]): DataNode[] {
  return sections.map((s) => ({
    key: s.id,
    title: `${s.title} (p.${s.page_start || '?'})`,
    children: s.children ? buildTreeData(s.children) : undefined,
  }))
}

const DocumentDetailPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selectedSubject, setSelectedSubject] = useState('')

  const { data: docData, isLoading } = useQuery({
    queryKey: ['document', id],
    queryFn: () => getDocumentDetail(id!),
    enabled: !!id,
  })

  const { data: sectionsData } = useQuery({
    queryKey: ['documentSections', id],
    queryFn: () => getDocumentSections(id!, true),
    enabled: !!id,
  })

  const { data: mappingsData } = useQuery({
    queryKey: ['sectionMappings', id],
    queryFn: () => getSectionMappings(id!),
    enabled: !!id,
  })

  const { data: subjectsData } = useQuery({
    queryKey: ['subjects'],
    queryFn: getSubjects,
  })

  const extractSectionsMut = useMutation({
    mutationFn: (force: boolean = false) => extractDocumentSections(id!, force),
    onSuccess: () => {
      message.success('标题树提取完成')
      queryClient.invalidateQueries({ queryKey: ['documentSections', id] })
      queryClient.invalidateQueries({ queryKey: ['sectionMappings', id] })
      queryClient.invalidateQueries({ queryKey: ['chapterDiagnostics', id] })
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      if (typeof detail === 'string' && detail.includes('无需重复提取')) {
        message.info(detail)
        queryClient.invalidateQueries({ queryKey: ['documentSections', id] })
        queryClient.invalidateQueries({ queryKey: ['chapterDiagnostics', id] })
      }
    },
  })

  const mapChaptersMut = useMutation({
    mutationFn: (force: boolean = false) => mapDocumentChapters(id!, selectedSubject || undefined, force),
    onSuccess: () => {
      message.success('章节映射完成')
      queryClient.invalidateQueries({ queryKey: ['document', id] })
      queryClient.invalidateQueries({ queryKey: ['sectionMappings', id] })
      queryClient.invalidateQueries({ queryKey: ['chapterDiagnostics', id] })
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      if (typeof detail === 'string' && detail.includes('无需重复执行')) {
        message.info(detail)
        queryClient.invalidateQueries({ queryKey: ['sectionMappings', id] })
        queryClient.invalidateQueries({ queryKey: ['chapterDiagnostics', id] })
      }
    },
  })

  const extractEntitiesMut = useMutation({
    mutationFn: () => extractDocumentEntities(id!, selectedSubject || document?.subject_id),
    onSuccess: (res) => {
      const result = res?.data
      message.success(`抽取完成：知识点 ${result?.knowledge_count ?? 0}，题目 ${result?.question_count ?? 0}`)
      queryClient.invalidateQueries({ queryKey: ['document', id] })
      queryClient.invalidateQueries({ queryKey: ['chapterDiagnostics', id] })
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      message.error(typeof detail === 'string' ? detail : '抽取失败')
    },
  })

  const document = docData?.data
  const sections = sectionsData?.data || []
  const mappings = mappingsData?.data || []
  const subjects = subjectsData?.data || []
  const treeData = buildTreeData(Array.isArray(sections) ? sections : [])
  const hasSections = treeData.length > 0
  const hasMappings = mappings.length > 0
  const isExamDoc = !!document && EXAM_DOC_TYPES.has(document.doc_type || '')

  const mappingStats = useMemo(() => {
    const counter = { approved: 0, pending: 0, rejected: 0 }
    for (const m of mappings as any[]) {
      const key = m.review_status as keyof typeof counter
      if (key in counter) counter[key] += 1
    }
    return { ...counter, total: mappings.length }
  }, [mappings])

  if (isLoading) {
    return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  }

  if (!document) {
    return <Empty description="文档不存在" />
  }

  const mappingColumns = [
    { title: '原生标题', dataIndex: 'section_title', key: 'section_title', ellipsis: true },
    { title: '映射章节', dataIndex: 'canonical_chapter_name', key: 'canonical_chapter_name' },
    {
      title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 100,
      render: (v: number) => v ? `${(v * 100).toFixed(0)}%` : '-',
    },
    { title: '映射类型', dataIndex: 'mapping_type', key: 'mapping_type', width: 100 },
    {
      title: '审核状态', dataIndex: 'review_status', key: 'review_status', width: 100,
      render: (s: string) => {
        const cfg = reviewStatusConfig[s] || { color: 'default', text: s }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
  ]

  const extractSectionsTip = hasSections ? '删除当前标题树和章节映射后重新从 blocks 识别' : '从已解析的 blocks 中识别文档原始章节结构'
  const mapChaptersTip = hasMappings ? '删除当前章节映射后重新匹配标准章节体系' : '将原生标题树映射到系统标准章节体系'
  const extractSectionsButtonText = hasSections ? '重新提取标题树' : '提取标题树'
  const mapChaptersButtonText = hasMappings ? '重新映射章节' : '映射到标准章节'

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/corpus')} style={{ marginBottom: 16 }}>
        返回列表
      </Button>

      <Card style={{ marginBottom: 16 }}>
        <Descriptions title="文档信息" column={2}>
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

      {!isExamDoc && (
        <Card style={{ marginBottom: 16 }}>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="原生标题树是从文档内容里识别出来的章节标题（教材自带的章节结构）；映射到标准章节是把这些原生标题挂到系统维护的学科章节体系上，供后续知识点和题目归属使用。试卷类文档不走这一层。"
          />
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h4 style={{ margin: 0 }}><ApartmentOutlined style={{ marginRight: 8 }} />原生标题树</h4>
            <Space>
              <Tooltip title={extractSectionsTip}>
                <Button
                  icon={<NodeIndexOutlined />}
                  loading={extractSectionsMut.isPending}
                  onClick={() => {
                    if (hasSections) {
                      Modal.confirm({
                        title: '重新提取标题树',
                        content: '将删除当前标题树和章节映射后重新生成，确认继续？',
                        onOk: () => extractSectionsMut.mutate(true),
                      })
                    } else {
                      extractSectionsMut.mutate(false)
                    }
                  }}
                >
                  {extractSectionsButtonText}
                </Button>
              </Tooltip>
              <Select
                placeholder="全部学科（自动识别）"
                style={{ width: 180 }}
                value={selectedSubject || undefined}
                onChange={setSelectedSubject}
                allowClear
                options={subjects.map((s: any) => ({ label: s.name, value: s.id }))}
              />
              <Tooltip title={mapChaptersTip}>
                <Button
                  type="primary"
                  loading={mapChaptersMut.isPending}
                  disabled={!hasSections}
                  onClick={() => {
                    if (hasMappings) {
                      Modal.confirm({
                        title: '重新映射章节',
                        content: '将删除当前章节映射后重新匹配标准章节，确认继续？',
                        onOk: () => mapChaptersMut.mutate(true),
                      })
                    } else {
                      mapChaptersMut.mutate(false)
                    }
                  }}
                >
                  {mapChaptersButtonText}
                </Button>
              </Tooltip>
            </Space>
          </div>
          {treeData.length > 0 ? (
            <Tree treeData={treeData} defaultExpandAll showLine />
          ) : (
            <Empty description="暂无标题树，请先提取" />
          )}
        </Card>
      )}

      {isExamDoc && (
        <Card style={{ marginBottom: 16 }}>
          <Alert
            type="warning"
            showIcon
            message="试卷类文档没有原生章节结构"
            description="本文档为试卷类型，题目应在抽取阶段直接挂到学科+标准章节上。无需提取标题树或建立章节映射。下方仅展示页级归属诊断和页级对比工具。"
          />
          <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Space>
              <Select
                placeholder="选择兜底学科（必选）"
                style={{ width: 200 }}
                value={selectedSubject || document.subject_id || undefined}
                onChange={setSelectedSubject}
                allowClear
                options={subjects.map((s: any) => ({ label: s.name, value: s.id }))}
              />
              <Button
                type="primary"
                icon={<ExperimentOutlined />}
                loading={extractEntitiesMut.isPending}
                onClick={() => Modal.confirm({
                  title: '确认抽取',
                  content: '将从文档中抽取题目并挂到指定学科，确认继续？',
                  onOk: () => extractEntitiesMut.mutate(),
                })}
              >
                抽取题目
              </Button>
            </Space>
          </div>
        </Card>
      )}

      <Card>
        <Tabs
          defaultActiveKey={isExamDoc ? 'chapter-diagnostics' : 'sections'}
          items={[
            ...(isExamDoc ? [] : [{
              key: 'sections',
              label: '原生标题 → 标准章节映射',
              children: (
                <>
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                    message="本表展示「文档原生标题」与「系统标准章节」的对应关系。每行 = 一个原生标题被映射到了哪个标准章节。这不是题目列表 — 题目数量见下方「章节归属诊断」或「题目管理」页面。"
                  />
                  {hasMappings && (
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={6}>
                        <Card size="small"><Statistic title="总映射数" value={mappingStats.total} /></Card>
                      </Col>
                      <Col span={6}>
                        <Card size="small"><Statistic title="自动通过" value={mappingStats.approved} valueStyle={{ color: '#52c41a' }} /></Card>
                      </Col>
                      <Col span={6}>
                        <Card size="small"><Statistic title="待审核" value={mappingStats.pending} valueStyle={{ color: '#faad14' }} /></Card>
                      </Col>
                      <Col span={6}>
                        <Card size="small"><Statistic title="已拒绝" value={mappingStats.rejected} valueStyle={{ color: '#ff4d4f' }} /></Card>
                      </Col>
                    </Row>
                  )}
                  <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h4 style={{ margin: 0 }}>映射明细（{mappings.length} 条）</h4>
                    <Button
                      icon={<ExperimentOutlined />}
                      loading={extractEntitiesMut.isPending}
                      disabled={!hasMappings}
                      onClick={() => Modal.confirm({
                        title: '确认抽取',
                        content: '将从文档中抽取知识点和题目，确认继续？',
                        onOk: () => extractEntitiesMut.mutate(),
                      })}
                    >
                      抽取知识点/题目
                    </Button>
                  </div>
                  {mappings.length > 0 ? (
                    <Table dataSource={mappings} columns={mappingColumns} rowKey="mapping_id" pagination={{ pageSize: 20, showSizeChanger: true }} />
                  ) : (
                    <Empty description="暂无映射结果，请先映射到标准章节" />
                  )}
                </>
              ),
            }]),
            {
              key: 'chapter-diagnostics',
              label: '章节归属诊断',
              children: (
                <ChapterDiagnostics
                  documentId={id!}
                  totalPages={document?.page_count || document?.pages?.length || 0}
                />
              ),
            },
            {
              key: 'page-analysis',
              label: '页级对比',
              children: (
                <PageAnalysis
                  documentId={id!}
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
