import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Tag, Space, Descriptions, message, Spin, Empty, Select, Modal, Alert, Tabs } from 'antd'
import { ArrowLeftOutlined, ExperimentOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getDocumentDetail, extractDocumentEntities, getSubjects } from '@/api'
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
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selectedSubject, setSelectedSubject] = useState('')

  const { data: docData, isLoading } = useQuery({
    queryKey: ['document', id],
    queryFn: () => getDocumentDetail(id!),
    enabled: !!id,
  })

  const { data: subjectsData } = useQuery({
    queryKey: ['subjects'],
    queryFn: getSubjects,
  })

  const document = docData?.data
  const subjects = subjectsData?.data || []
  const isExamDoc = !!document && EXAM_DOC_TYPES.has(document.doc_type || '')

  const extractEntitiesMut = useMutation({
    mutationFn: () => extractDocumentEntities(id!, selectedSubject || document?.subject_id),
    onSuccess: (res) => {
      const result = res?.data
      message.success(`抽取完成：知识点 ${result?.knowledge_count ?? 0}，题目 ${result?.question_count ?? 0}`)
      queryClient.invalidateQueries({ queryKey: ['document', id] })
      queryClient.invalidateQueries({ queryKey: ['contentOverview', id] })
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      message.error(typeof detail === 'string' ? detail : '抽取失败')
    },
  })

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

      <Card style={{ marginBottom: 16 }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="抽取知识点/题目时，系统会直接把每个实体挂到学科+标准章节上（不再需要先做原生标题映射与审核）。下方「内容总览」按章节展示知识点、按题号展示题目；「页级对比」用于核对每页解析质量。"
        />
        <Space>
          <Select
            placeholder={isExamDoc ? '选择兜底学科（必选）' : '全部学科（自动识别）'}
            style={{ width: 220 }}
            value={selectedSubject || (isExamDoc ? document.subject_id : undefined) || undefined}
            onChange={setSelectedSubject}
            allowClear
            options={subjectOptions}
          />
          <Button
            type="primary"
            icon={<ExperimentOutlined />}
            loading={extractEntitiesMut.isPending}
            onClick={() => Modal.confirm({
              title: '确认抽取',
              content: isExamDoc
                ? '将从文档中抽取题目并挂到指定学科+标准章节，确认继续？'
                : '将从文档中抽取知识点和题目并挂到标准章节，确认继续？',
              onOk: () => extractEntitiesMut.mutate(),
            })}
          >
            {isExamDoc ? '抽取题目' : '抽取知识点/题目'}
          </Button>
        </Space>
      </Card>

      <Card>
        <Tabs
          defaultActiveKey="content-overview"
          items={[
            {
              key: 'content-overview',
              label: '内容总览',
              children: <ContentOverview documentId={id!} />,
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
