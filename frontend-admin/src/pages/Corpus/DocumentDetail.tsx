import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Tree, Table, Tag, Space, Descriptions, message, Spin, Empty, Select, Modal } from 'antd'
import { ArrowLeftOutlined, ApartmentOutlined, NodeIndexOutlined, ExperimentOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getDocumentDetail, getDocumentSections, getSectionMappings, extractDocumentSections, mapDocumentChapters, extractDocumentEntities, getSubjects } from '@/api'
import type { DataNode } from 'antd/es/tree'

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
    mutationFn: () => extractDocumentSections(id!),
    onSuccess: () => {
      message.success('标题树提取完成')
      queryClient.invalidateQueries({ queryKey: ['documentSections', id] })
      queryClient.invalidateQueries({ queryKey: ['sectionMappings', id] })
    },
  })

  const mapChaptersMut = useMutation({
    mutationFn: () => mapDocumentChapters(id!, selectedSubject || undefined),
    onSuccess: () => {
      message.success('章节映射完成')
      queryClient.invalidateQueries({ queryKey: ['document', id] })
      queryClient.invalidateQueries({ queryKey: ['sectionMappings', id] })
    },
  })

  const extractEntitiesMut = useMutation({
    mutationFn: () => extractDocumentEntities(id!),
    onSuccess: () => {
      message.success(`抽取完成`)
      queryClient.invalidateQueries({ queryKey: ['document', id] })
    },
  })

  const document = docData?.data
  const sections = sectionsData?.data || []
  const mappings = mappingsData?.data || []
  const subjects = subjectsData?.data || []
  const treeData = buildTreeData(Array.isArray(sections) ? sections : [])

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

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/corpus')} style={{ marginBottom: 16 }}>
        返回列表
      </Button>

      <Card style={{ marginBottom: 16 }}>
        <Descriptions title="文档信息" column={2}>
          <Descriptions.Item label="文件名">{document.file_name || document.title || '-'}</Descriptions.Item>
          <Descriptions.Item label="状态">{document.status}</Descriptions.Item>
          <Descriptions.Item label="页数">{document.page_count || document.pages?.length || '-'}</Descriptions.Item>
          <Descriptions.Item label="Block 数">{document.block_count || document.blocks?.length || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {document.created_at ? new Date(document.created_at).toLocaleString('zh-CN') : '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h4 style={{ margin: 0 }}><ApartmentOutlined style={{ marginRight: 8 }} />原生标题树</h4>
          <Space>
            <Button icon={<NodeIndexOutlined />} loading={extractSectionsMut.isPending} onClick={() => extractSectionsMut.mutate()}>
              提取标题树
            </Button>
            <Select
              placeholder="全部学科（自动识别）"
              style={{ width: 180 }}
              value={selectedSubject || undefined}
              onChange={setSelectedSubject}
              allowClear
              options={subjects.map((s: any) => ({ label: s.name, value: s.id }))}
            />
            <Button type="primary" loading={mapChaptersMut.isPending} onClick={() => mapChaptersMut.mutate()}>
              映射到标准章节
            </Button>
          </Space>
        </div>
        {treeData.length > 0 ? (
          <Tree treeData={treeData} defaultExpandAll showLine />
        ) : (
          <Empty description="暂无标题树，请先提取" />
        )}
      </Card>

      <Card>
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h4 style={{ margin: 0 }}>Section 映射</h4>
          <Button
            icon={<ExperimentOutlined />}
            loading={extractEntitiesMut.isPending}
            onClick={() => Modal.confirm({
              title: '确认抽取',
              content: '将从文档中抽取知识点和题目，确认继续？',
              onOk: () => extractEntitiesMut.mutate(),
            })}
          >
            抽取知识点/题目
          </Button>
        </div>
        <Table dataSource={mappings} columns={mappingColumns} rowKey="mapping_id" pagination={false} size="small" />
      </Card>
    </div>
  )
}

export default DocumentDetailPage
