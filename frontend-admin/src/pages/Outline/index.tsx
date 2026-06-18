import { useState } from 'react'
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, InputNumber, Select,
  Switch, Upload, Tree, message, Alert, Descriptions, Spin,
} from 'antd'
import {
  PlusOutlined, InboxOutlined, EyeOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listOutlines, getOutlineChapters, uploadParseOutline, importOutlineFromDocument,
  getSubjects,
  type OutlineSummary, type OutlineChapter, type OutlineUploadParseResult, type OutlinePreviewItem,
} from '@/api'

const { Dragger } = Upload

const buildTreeNodes = (chapters: OutlinePreviewItem[] | OutlineChapter[]): any[] => {
  return chapters.map((c) => {
    const code = (c as OutlinePreviewItem).outline_code || (c as OutlineChapter).outline_code
    const title = code ? `${code} ${c.name}` : c.name
    const children = (c.children || []) as any[]
    return {
      title,
      key: `${title}-${Math.random()}`,
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

  const { data: outlinesRes } = useQuery({ queryKey: ['outlines'], queryFn: listOutlines })
  const { data: subjectsRes } = useQuery({ queryKey: ['subjects'], queryFn: getSubjects })

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
        message.success(`解析完成：识别 ${res.data.total_chapters} 个章节，深度 ${res.data.max_depth}`)
      }
    },
    onError: (err: any) => {
      message.error('解析失败: ' + (err?.response?.data?.detail || err.message))
    },
  })

  const importMut = useMutation({
    mutationFn: (values: any) =>
      importOutlineFromDocument({
        subject_id: values.subject_id,
        document_id: parsed!.document_id,
        name: values.name,
        year: values.year,
        version: values.version || 'v1.0',
        set_default: !!values.set_default,
      }),
    onSuccess: (res) => {
      const r = res.data
      message.success(`导入成功：新建 ${r?.created_chapters} 个，更新 ${r?.updated_chapters} 个`)
      qc.invalidateQueries({ queryKey: ['outlines'] })
      resetImport()
    },
    onError: (err: any) => message.error('导入失败：' + (err?.response?.data?.detail || err.message)),
  })

  const { data: chaptersRes, isLoading: chaptersLoading } = useQuery({
    queryKey: ['outlineChapters', chapterDrawer.outline?.id],
    queryFn: () => getOutlineChapters(chapterDrawer.outline!.id),
    enabled: !!chapterDrawer.open && !!chapterDrawer.outline,
  })

  const outlines = outlinesRes?.data || []
  const subjects = subjectsRes?.data || []

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
      title: '操作', key: 'actions', width: 120,
      render: (_: unknown, r: OutlineSummary) => (
        <Button type="link" icon={<EyeOutlined />}
          onClick={() => setChapterDrawer({ outline: r, open: true })}>查看章节</Button>
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

      {/* 导入大纲弹窗：PDF 解析 → 标题树预览 → 入库 */}
      <Modal
        title="导入大纲（PDF 解析）"
        open={importModalOpen}
        onCancel={resetImport}
        footer={null}
        width={900}
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Alert
            type="info"
            showIcon
            message="上传大纲 PDF 自动解析"
            description="系统会解析 PDF 的标题层级（章/节/条），生成大纲章节树。大纲走标题树识别，不经过题目的题干/选项分离逻辑。支持 PDF / DOCX / PPTX。"
          />

          <Dragger
            beforeUpload={beforeUpload}
            showUploadList={false}
            accept=".pdf,.docx,.pptx"
            disabled={uploadMut.isPending}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽大纲文件到此处</p>
            <p className="ant-upload-hint">解析较大文件可能需要数十秒，请耐心等待</p>
          </Dragger>

          {uploadMut.isPending && (
            <div style={{ textAlign: 'center', padding: 16 }}>
              <Spin tip="正在解析文件并提取标题树…" />
            </div>
          )}

          {parsed && (
            <Card size="small" title={`标题树预览（${parsed.file_name}，共 ${parsed.total_chapters} 节，深度 ${parsed.max_depth}）`}>
              {parsed.total_chapters === 0 ? (
                <Alert type="warning" message="未识别到标题层级，请确认该文件含有章节标题结构" />
              ) : (
                <Tree
                  treeData={buildTreeNodes(parsed.chapters)}
                  defaultExpandAll={parsed.total_chapters < 50}
                  showLine
                  height={360}
                />
              )}
            </Card>
          )}

          {parsed && parsed.total_chapters > 0 && (
            <Card size="small" title="入库设置">
              <Form form={form} layout="vertical" onFinish={(v) => importMut.mutate(v)}>
                <Space wrap>
                  <Form.Item name="subject_id" label="学科" rules={[{ required: true }]} style={{ minWidth: 200 }}>
                    <Select placeholder="选择学科" options={subjects.map((s: any) => ({ label: s.name, value: s.id }))} />
                  </Form.Item>
                  <Form.Item name="name" label="大纲名称" rules={[{ required: true }]} style={{ minWidth: 220 }}>
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

      {/* 章节查看 */}
      <Modal
        title={chapterDrawer.outline ? `章节 - ${chapterDrawer.outline.name}` : '章节'}
        open={chapterDrawer.open}
        onCancel={() => setChapterDrawer({ outline: null, open: false })}
        footer={null}
        width={720}
      >
        {chapterDrawer.outline && (
          <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="年份">{chapterDrawer.outline.year}</Descriptions.Item>
            <Descriptions.Item label="版本">{chapterDrawer.outline.version}</Descriptions.Item>
            <Descriptions.Item label="状态">{chapterDrawer.outline.status}</Descriptions.Item>
            <Descriptions.Item label="默认">{chapterDrawer.outline.is_default ? '是' : '否'}</Descriptions.Item>
          </Descriptions>
        )}
        {chaptersLoading ? <Spin /> : (
          <Tree
            treeData={buildTreeNodes(chaptersRes?.data || [])}
            defaultExpandAll={(chaptersRes?.data || []).length < 30}
            showLine
          />
        )}
      </Modal>
    </div>
  )
}

export default OutlineList
