import { useState } from 'react'
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, InputNumber, Select,
  Switch, Upload, Tree, message, Tabs, Alert, Descriptions, Spin,
} from 'antd'
import {
  PlusOutlined, UploadOutlined, EyeOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listOutlines, getOutlineChapters, previewOutline, importOutline,
  getSubjects,
  type OutlineSummary, type OutlineChapter, type OutlinePreview, type OutlinePreviewItem,
} from '@/api'

const { TextArea } = Input

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
  const [content, setContent] = useState('')
  const [filename, setFilename] = useState('')
  const [preview, setPreview] = useState<OutlinePreview | null>(null)
  const [chapterDrawer, setChapterDrawer] = useState<{ outline: OutlineSummary | null; open: boolean }>({ outline: null, open: false })

  const { data: outlinesRes } = useQuery({ queryKey: ['outlines'], queryFn: listOutlines })
  const { data: subjectsRes } = useQuery({ queryKey: ['subjects'], queryFn: getSubjects })

  const previewMut = useMutation({
    mutationFn: () => previewOutline(content, filename),
    onSuccess: (res) => {
      if (res.data) {
        setPreview(res.data)
        message.success(`已解析 ${res.data.total_chapters} 个章节，深度 ${res.data.max_depth}`)
      }
    },
    onError: (err: any) => {
      message.error('解析失败: ' + (err?.response?.data?.detail || err.message))
    },
  })

  const importMut = useMutation({
    mutationFn: (values: any) =>
      importOutline({
        subject_id: values.subject_id,
        name: values.name,
        year: values.year,
        version: values.version || 'v1.0',
        description: values.description,
        set_default: !!values.set_default,
        content,
        filename,
      }),
    onSuccess: (res) => {
      const r = res.data
      message.success(`导入成功：新建 ${r?.created_chapters} 个，更新 ${r?.updated_chapters} 个`)
      qc.invalidateQueries({ queryKey: ['outlines'] })
      setImportModalOpen(false)
      form.resetFields()
      setContent('')
      setFilename('')
      setPreview(null)
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

  const handleFileUpload = (file: File) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      const text = String(e.target?.result || '')
      setContent(text)
      setFilename(file.name)
      message.success(`已读取 ${file.name}（${text.length} 字符）`)
    }
    reader.readAsText(file, 'utf-8')
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

      {/* 导入大纲弹窗 */}
      <Modal
        title="导入大纲"
        open={importModalOpen}
        onCancel={() => setImportModalOpen(false)}
        footer={null}
        width={900}
      >
        <Tabs
          items={[
            {
              key: 'paste',
              label: '粘贴文本/JSON',
              children: (
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <Alert
                    type="info"
                    message="支持两种格式"
                    description={
                      <div>
                        <div>1. <b>JSON</b>：[{`{"name": "数据结构", "children": [...]}`}]</div>
                        <div>2. <b>纯文本</b>：每行一章节，支持 1.1.1 / 第一章 / 一、 / (一) 等编号自动识别层级</div>
                      </div>
                    }
                  />
                  <Upload beforeUpload={handleFileUpload} showUploadList={false}
                    accept=".txt,.md,.json">
                    <Button icon={<UploadOutlined />}>从文件加载</Button>
                  </Upload>
                  {filename && <span style={{ color: '#666', fontSize: 12 }}>已加载：{filename}</span>}
                  <TextArea
                    rows={12}
                    value={content}
                    onChange={(e) => { setContent(e.target.value); setPreview(null) }}
                    placeholder="粘贴大纲内容，或从上方加载文件…"
                    style={{ fontFamily: 'monospace', fontSize: 13 }}
                  />
                  <Button onClick={() => previewMut.mutate()} loading={previewMut.isPending}
                    disabled={!content.trim()}>解析预览</Button>

                  {preview && (
                    <Card size="small" title={`预览（${preview.format}, 共 ${preview.total_chapters} 节, 深度 ${preview.max_depth}）`}>
                      <Tree
                        treeData={buildTreeNodes(preview.chapters)}
                        defaultExpandAll={preview.total_chapters < 50}
                        showLine
                      />
                    </Card>
                  )}

                  {preview && (
                    <Card size="small" title="入库设置">
                      <Form form={form} layout="vertical" onFinish={(v) => importMut.mutate(v)}>
                        <Space>
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
                        <Form.Item name="description" label="说明">
                          <TextArea rows={2} placeholder="可选说明" />
                        </Form.Item>
                        <Button type="primary" htmlType="submit" loading={importMut.isPending}>确认导入</Button>
                      </Form>
                    </Card>
                  )}
                </Space>
              ),
            },
          ]}
        />
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
