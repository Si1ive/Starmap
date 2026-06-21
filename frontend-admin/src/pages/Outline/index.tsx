import { useState } from 'react'
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, InputNumber,
  Switch, Upload, Tree, message, Alert, Descriptions, Spin, Tabs, Typography, Popconfirm,
} from 'antd'
import {
  PlusOutlined, InboxOutlined, EyeOutlined, CheckCircleOutlined, BulbOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listOutlines, getOutlineChapters, getOutlineSubjects, uploadParseOutline,
  importOutlineFromLLM, generateOutlineGuidance, deleteOutline,
  type OutlineSummary, type OutlineChapter, type OutlineUploadParseResult,
  type OutlinePreviewItem, type OutlineSubjectInfo,
} from '@/api'

const { Dragger } = Upload
const { Paragraph, Text: AntText } = Typography

const buildTreeNodes = (chapters: OutlinePreviewItem[] | OutlineChapter[]): any[] => {
  return chapters.map((c, i) => {
    const code = (c as OutlinePreviewItem).outline_code || (c as OutlineChapter).outline_code
    const title = code ? `${code} ${c.name}` : c.name
    const guidance = (c as any).exam_guidance
    const desc = (c as any).description
    const children = (c.children || []) as any[]
    return {
      title: (
        <span>
          {title}
          {desc ? <AntText type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>· 考点</AntText> : null}
          {guidance ? <Tag color="gold" style={{ marginLeft: 8, fontSize: 11 }}>复习指导</Tag> : null}
        </span>
      ),
      key: `${title}-${i}-${Math.random()}`,
      children: children.length ? buildTreeNodes(children) : undefined,
    }
  })
}

const OutlineList = () => {
  const qc = useQueryClient()
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [parsed, setParsed] = useState<OutlineUploadParseResult | null>(null)
  const [chapterDrawer, setChapterDrawer] = useState<{ outline: OutlineSummary | null; open: boolean }>({ outline: null, open: false })
  const [activeSubject, setActiveSubject] = useState<string>('')

  const { data: outlinesRes } = useQuery({ queryKey: ['outlines'], queryFn: listOutlines })

  const resetImport = () => {
    setImportModalOpen(false)
    form.resetFields()
    setParsed(null)
  }

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadParseOutline(file),
    onSuccess: (res) => {
      if (res.data) {
        setParsed(res.data)
        const total = (res.data.subjects || []).reduce((s, x) => s + x.total_chapters, 0)
        message.success(`解析完成：识别 ${res.data.subjects?.length || 0} 门课，共 ${total} 个章节`)
      }
    },
    onError: (err: any) => {
      message.error('解析失败: ' + (err?.response?.data?.detail || err.message))
    },
  })

  const importMut = useMutation({
    mutationFn: (values: any) =>
      importOutlineFromLLM({
        name: values.name,
        year: values.year,
        version: values.version || 'v1.0',
        set_default: !!values.set_default,
        subjects: parsed!.subjects,
      }),
    onSuccess: (res) => {
      const r = res.data
      message.success(`导入成功：新建 ${r?.created_chapters} 个，更新 ${r?.updated_chapters} 个章节`)
      qc.invalidateQueries({ queryKey: ['outlines'] })
      resetImport()
    },
    onError: (err: any) => message.error('导入失败：' + (err?.response?.data?.detail || err.message)),
  })

  // 章节查看：先取该大纲的科目列表，再按选中科目取章节树
  const { data: outlineSubjectsRes } = useQuery({
    queryKey: ['outlineSubjects', chapterDrawer.outline?.id],
    queryFn: () => getOutlineSubjects(chapterDrawer.outline!.id),
    enabled: !!chapterDrawer.open && !!chapterDrawer.outline,
  })
  const outlineSubjects = outlineSubjectsRes?.data || []
  const currentSubject = activeSubject || outlineSubjects[0]?.subject_id || ''

  const { data: chaptersRes, isLoading: chaptersLoading } = useQuery({
    queryKey: ['outlineChapters', chapterDrawer.outline?.id, currentSubject],
    queryFn: () => getOutlineChapters(chapterDrawer.outline!.id, currentSubject),
    enabled: !!chapterDrawer.open && !!chapterDrawer.outline && !!currentSubject,
  })

  const guidanceMut = useMutation({
    mutationFn: (subjectId: string) => generateOutlineGuidance(chapterDrawer.outline!.id, subjectId),
    onSuccess: (res) => {
      message.success(`复习指导已生成：${res.data?.updated_chapters}/${res.data?.total_chapters} 个章节`)
      qc.invalidateQueries({ queryKey: ['outlineSubjects', chapterDrawer.outline?.id] })
      qc.invalidateQueries({ queryKey: ['outlineChapters', chapterDrawer.outline?.id] })
    },
    onError: (err: any) => message.error('生成失败：' + (err?.response?.data?.detail || err.message)),
  })

  const deleteMut = useMutation({
    mutationFn: (outlineId: string) => deleteOutline(outlineId),
    onSuccess: (res) => {
      message.success(`已删除大纲《${res.data?.outline_name}》及其 ${res.data?.deleted_chapters} 个章节`)
      qc.invalidateQueries({ queryKey: ['outlines'] })
    },
    onError: (err: any) => message.error('删除失败：' + (err?.response?.data?.detail || err.message)),
  })

  const outlines = outlinesRes?.data || []

  const beforeUpload = (file: File) => {
    const ext = file.name.split('.').pop()?.toLowerCase()
    if (!ext || !['pdf', 'docx', 'pptx'].includes(ext)) {
      message.error('仅支持 PDF / DOCX / PPTX 文件')
      return Upload.LIST_IGNORE
    }
    setParsed(null)
    uploadMut.mutate(file)
    return false
  }

  const columns = [
    { title: '名称', dataIndex: 'name' },
    { title: '年份', dataIndex: 'year', width: 80 },
    { title: '版本', dataIndex: 'version', width: 100 },
    { title: '状态', dataIndex: 'status', width: 100, render: (s: string) => <Tag color={s === 'active' ? 'success' : 'default'}>{s}</Tag> },
    {
      title: '默认', dataIndex: 'is_default', width: 80,
      render: (v: boolean) => v ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : '-',
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'actions', width: 180,
      render: (_: unknown, r: OutlineSummary) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />}
            onClick={() => setChapterDrawer({ outline: r, open: true })}>查看章节</Button>
          <Popconfirm
            title="确认删除此大纲？"
            description={`将删除《${r.name}》及其所有章节，此操作不可恢复！`}
            onConfirm={() => deleteMut.mutate(r.id)}
            okText="确认删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}
              loading={deleteMut.isPending && deleteMut.variables === r.id}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>大纲管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setImportModalOpen(true)}>导入大纲</Button>
      </div>

      <Card>
        <Table dataSource={outlines} columns={columns} rowKey="id" pagination={false} size="small" />
      </Card>

      {/* 导入大纲弹窗：PDF 解析 → LLM 拆分四门课预览 → 入库 */}
      <Modal
        title="导入大纲（PDF + LLM 拆分）"
        open={importModalOpen}
        onCancel={resetImport}
        footer={null}
        width={960}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Alert
            type="info"
            showIcon
            message="上传 408 大纲 PDF，自动拆分四门课"
            description="系统先用 MinerU 全文解析，再让 LLM 按四门课拆出考察目标 + 多层章节树（含原文考点）。复习指导在入库后单独生成。支持 PDF / DOCX / PPTX。"
          />

          <Dragger
            beforeUpload={beforeUpload}
            showUploadList={false}
            accept=".pdf,.docx,.pptx"
            disabled={uploadMut.isPending}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽大纲文件到此处</p>
            <p className="ant-upload-hint">解析 + LLM 拆分较耗时，可能需要数分钟，请耐心等待</p>
          </Dragger>

          {uploadMut.isPending && (
            <div style={{ textAlign: 'center', padding: 16 }}>
              <Spin tip="正在解析文件并用 LLM 拆分四门课…" />
            </div>
          )}

          {parsed && (parsed.subjects?.length || 0) > 0 && (
            <Card size="small" title={`拆分预览（${parsed.file_name}，${parsed.subjects.length} 门课）`}>
              <Tabs
                items={parsed.subjects.map((s) => ({
                  key: s.subject_id,
                  label: `${s.subject_name}（${s.total_chapters}）`,
                  children: (
                    <Space direction="vertical" style={{ width: '100%' }}>
                      {s.exam_objective && (
                        <Alert
                          type="success"
                          message="考察目标"
                          description={<Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{s.exam_objective}</Paragraph>}
                        />
                      )}
                      <Tree
                        treeData={buildTreeNodes(s.chapters)}
                        defaultExpandAll={s.total_chapters < 40}
                        showLine
                        height={320}
                      />
                    </Space>
                  ),
                }))}
              />
            </Card>
          )}

          {parsed && (parsed.subjects?.length || 0) === 0 && (
            <Alert type="warning" message="LLM 未拆分出任何科目，请检查大纲内容或 outline_llm 配置" />
          )}

          {parsed && (parsed.subjects?.length || 0) > 0 && (
            <Card size="small" title="入库设置（四门课一次入库）">
              <Form form={form} layout="vertical" onFinish={(v) => importMut.mutate(v)}>
                <Space wrap>
                  <Form.Item name="name" label="大纲名称" rules={[{ required: true }]} style={{ minWidth: 240 }}>
                    <Input placeholder="如：2025 年 408 大纲" />
                  </Form.Item>
                  <Form.Item name="year" label="年份" rules={[{ required: true }]}>
                    <InputNumber min={2000} max={2100} placeholder="2025" />
                  </Form.Item>
                  <Form.Item name="version" label="版本" initialValue="v1.0">
                    <Input placeholder="v1.0" />
                  </Form.Item>
                  <Form.Item name="set_default" label="设为默认" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </Space>
                <Button type="primary" htmlType="submit" loading={importMut.isPending}>确认导入</Button>
              </Form>
            </Card>
          )}
        </Space>
      </Modal>

      {/* 章节查看：按科目分 Tab，展示考察目标 + 章节树 + 复习指导生成 */}
      <Modal
        title={chapterDrawer.outline ? `章节 - ${chapterDrawer.outline.name}` : '章节'}
        open={chapterDrawer.open}
        onCancel={() => { setChapterDrawer({ outline: null, open: false }); setActiveSubject('') }}
        footer={null}
        width={820}
      >
        {chapterDrawer.outline && (
          <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="年份">{chapterDrawer.outline.year}</Descriptions.Item>
            <Descriptions.Item label="版本">{chapterDrawer.outline.version}</Descriptions.Item>
            <Descriptions.Item label="状态">{chapterDrawer.outline.status}</Descriptions.Item>
            <Descriptions.Item label="默认">{chapterDrawer.outline.is_default ? '是' : '否'}</Descriptions.Item>
          </Descriptions>
        )}
        {outlineSubjects.length === 0 ? (
          <Alert type="info" message="该大纲暂无科目数据" />
        ) : (
          <Tabs
            activeKey={currentSubject}
            onChange={setActiveSubject}
            items={outlineSubjects.map((s: OutlineSubjectInfo) => ({
              key: s.subject_id,
              label: s.subject_name,
              children: (
                <Space direction="vertical" style={{ width: '100%' }}>
                  {s.exam_objective && (
                    <Alert type="success" message="考察目标"
                      description={<Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{s.exam_objective}</Paragraph>} />
                  )}
                  <Space>
                    <Tag color={s.guidance_status === 'done' ? 'success' : s.guidance_status === 'failed' ? 'error' : 'default'}>
                      复习指导：{s.guidance_status}
                    </Tag>
                    <Button size="small" icon={<BulbOutlined />}
                      loading={guidanceMut.isPending && guidanceMut.variables === s.subject_id}
                      onClick={() => guidanceMut.mutate(s.subject_id)}>
                      {s.guidance_status === 'done' ? '重新生成复习指导' : '生成复习指导'}
                    </Button>
                  </Space>
                  {chaptersLoading ? <Spin /> : (
                    <Tree
                      treeData={buildTreeNodes(chaptersRes?.data || [])}
                      defaultExpandAll={(chaptersRes?.data || []).length < 25}
                      showLine
                      onSelect={(_, info: any) => {
                        const node = info.node
                        if (node) Modal.info({
                          title: '章节详情',
                          width: 600,
                          content: <ChapterDetail nodeKey={node.key} chapters={chaptersRes?.data || []} />,
                        })
                      }}
                    />
                  )}
                </Space>
              ),
            }))}
          />
        )}
      </Modal>
    </div>
  )
}

// 在章节树里按 name 找节点，展示 description + exam_guidance
const findChapter = (chapters: OutlineChapter[], match: string): OutlineChapter | null => {
  for (const c of chapters) {
    const title = c.outline_code ? `${c.outline_code} ${c.name}` : c.name
    if (match.startsWith(title)) return c
    const inChild = findChapter(c.children || [], match)
    if (inChild) return inChild
  }
  return null
}

const ChapterDetail = ({ nodeKey, chapters }: { nodeKey: string; chapters: OutlineChapter[] }) => {
  const ch = findChapter(chapters, nodeKey)
  if (!ch) return <span>未找到章节信息</span>
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <div><strong>原文考点</strong><Paragraph style={{ whiteSpace: 'pre-wrap' }}>{ch.description || '（无）'}</Paragraph></div>
      <div><strong>复习指导</strong><Paragraph style={{ whiteSpace: 'pre-wrap' }}>{ch.exam_guidance || '（尚未生成）'}</Paragraph></div>
    </Space>
  )
}

export default OutlineList
