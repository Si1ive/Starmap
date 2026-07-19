import { useState } from 'react'
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, InputNumber,
  Switch, Upload, Tree, message, Alert, Descriptions, Spin, Tabs, Typography, Popconfirm, Progress,
} from 'antd'
import {
  PlusOutlined, InboxOutlined, EyeOutlined, CheckCircleOutlined, BulbOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listOutlines, getOutlineChapters, getOutlineSubjects, uploadParseOutline,
  importOutlineFromLLM, generateOutlineGuidance, deleteOutline,
  listOutlineRuns, deleteOutlineRun, batchDeleteOutlineRuns, getOutlineRunDetail,
  type OutlineSummary, type OutlineChapter,
  type OutlinePreviewItem, type OutlineSubjectInfo, type OutlineSubjectSplit,
  type OutlineRunListItem,
} from '@/api'
import PageHeader from '@/components/PageHeader'

const { Dragger } = Upload
const { Paragraph, Text } = Typography

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
          {desc ? <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>· 考点</Text> : null}
          {guidance ? <Tag color="gold" style={{ marginLeft: 8, fontSize: 11 }}>复习指导</Tag> : null}
        </span>
      ),
      key: `${title}-${i}-${Math.random()}`,
      children: children.length ? buildTreeNodes(children) : undefined,
    }
  })
}

const runStatusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '等待中' },
  processing: { color: 'processing', text: '处理中' },
  done: { color: 'success', text: '已完成' },
  partial: { color: 'warning', text: '部分成功' },
  failed: { color: 'error', text: '失败' },
}

const OutlineList = () => {
  const qc = useQueryClient()
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [splitSubjects, setSplitSubjects] = useState<OutlineSubjectSplit[] | null>(null)
  const [parsedFileName, setParsedFileName] = useState<string>('')
  const [detailRunId, setDetailRunId] = useState<string | null>(null) // 正在查看详情的 run_id，非 null 表示查看已完成任务
  const [chapterDrawer, setChapterDrawer] = useState<{ outline: OutlineSummary | null; open: boolean }>({ outline: null, open: false })
  const [activeSubject, setActiveSubject] = useState<string>('')
  const [selectedRunKeys, setSelectedRunKeys] = useState<React.Key[]>([])

  const { data: outlinesRes } = useQuery({ queryKey: ['outlines'], queryFn: listOutlines })

  // 任务列表：有 processing 状态的任务时自动轮询
  const { data: runsRes } = useQuery({
    queryKey: ['outlineRuns'],
    queryFn: () => listOutlineRuns({ limit: 100 }),
    refetchInterval: (queryData) => {
      const items = queryData?.data?.items || []
      return items.some((r: OutlineRunListItem) => r.status === 'processing') ? 3000 : false
    },
  })
  const runs: OutlineRunListItem[] = runsRes?.data?.items || []

  const resetImport = () => {
    setImportModalOpen(false)
    form.resetFields()
    setSplitSubjects(null)
    setParsedFileName('')
    setDetailRunId(null)
  }

  // 上传后立即拿到 run_id
  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadParseOutline(file),
    onSuccess: (res) => {
      if (res.data?.run_id) {
        setParsedFileName(res.data.file_name || '')
        setSplitSubjects(null)
        message.info('任务已启动，可在下方任务列表中查看进度')
        qc.invalidateQueries({ queryKey: ['outlineRuns'] })
      }
    },
    onError: (err: any) => {
      message.error('上传失败: ' + (err?.response?.data?.detail || err.message))
    },
  })

  // 查看任务详情：调详情接口获取 result_summary，打开弹窗
  const viewRunDetail = async (runItem: OutlineRunListItem) => {
    setImportModalOpen(true)
    setDetailRunId(runItem.id)
    setParsedFileName(runItem.outline_name || runItem.file_name || '')
    try {
      const detail = await getOutlineRunDetail(runItem.id)
      const r = detail.data
      setParsedFileName(r.outline_name || r.file_name || '')
      if (['done', 'partial'].includes(r.status) && r.result_summary?.subjects) {
        setSplitSubjects(r.result_summary.subjects)
      } else {
        setSplitSubjects(null)
      }
    } catch {
      if (['done', 'partial'].includes(runItem.status) && (runItem as any).result_summary?.subjects) {
        setSplitSubjects((runItem as any).result_summary.subjects)
      } else {
        setSplitSubjects(null)
      }
    }
  }

  const importMut = useMutation({
    mutationFn: (values: any) => {
      if (!splitSubjects) {
        throw new Error('没有可导入的科目数据')
      }
      return importOutlineFromLLM({
        name: values.name,
        year: values.year,
        version: values.version || 'v1.0',
        set_default: !!values.set_default,
        subjects: splitSubjects,
      })
    },
    onSuccess: (res) => {
      const r = res.data
      message.success(`导入成功：新建 ${r?.created_chapters} 个，更新 ${r?.updated_chapters} 个章节`)
      qc.invalidateQueries({ queryKey: ['outlines'] })
      qc.invalidateQueries({ queryKey: ['outlineRuns'] })
      resetImport()
    },
    onError: (err: any) => message.error('导入失败：' + (err?.response?.data?.detail || err.message)),
  })

  const deleteRunMut = useMutation({
    mutationFn: (runId: string) => deleteOutlineRun(runId),
    onSuccess: () => {
      message.success('任务记录已删除')
      qc.invalidateQueries({ queryKey: ['outlineRuns'] })
    },
    onError: (err: any) => message.error('删除失败：' + (err?.response?.data?.detail || err.message)),
  })

  const batchDeleteRunsMut = useMutation({
    mutationFn: (ids: string[]) => batchDeleteOutlineRuns(ids),
    onSuccess: (res) => {
      message.success(`已删除 ${res.data?.deleted_count || 0} 条任务记录`)
      setSelectedRunKeys([])
      qc.invalidateQueries({ queryKey: ['outlineRuns'] })
    },
    onError: (err: any) => message.error('批量删除失败：' + (err?.response?.data?.detail || err.message)),
  })

  // 章节查看：先取该大纲的科目列表，再按选中科目取章节树
  const selectedOutlineId = chapterDrawer.outline?.id
  const { data: outlineSubjectsRes } = useQuery({
    queryKey: ['outlineSubjects', selectedOutlineId],
    queryFn: () => getOutlineSubjects(selectedOutlineId ?? ''),
    enabled: chapterDrawer.open && !!selectedOutlineId,
  })
  const outlineSubjects = outlineSubjectsRes?.data || []
  const currentSubject = activeSubject || outlineSubjects[0]?.subject_id || ''

  const { data: chaptersRes, isLoading: chaptersLoading } = useQuery({
    queryKey: ['outlineChapters', selectedOutlineId, currentSubject],
    queryFn: () => getOutlineChapters(selectedOutlineId ?? '', currentSubject),
    enabled: chapterDrawer.open && !!selectedOutlineId && !!currentSubject,
  })

  const guidanceMut = useMutation({
    mutationFn: (subjectId: string) => {
      if (!selectedOutlineId) {
        throw new Error('请先选择考试大纲')
      }
      return generateOutlineGuidance(selectedOutlineId, subjectId)
    },
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
    if (ext !== 'pdf') {
      message.error('仅支持 PDF 文件')
      return Upload.LIST_IGNORE
    }
    setSplitSubjects(null)
    uploadMut.mutate(file)
    return false
  }

  const outlineColumns = [
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

  const runColumns = [
    {
      title: '文件名', dataIndex: 'outline_name', ellipsis: true,
      render: (name: string, r: OutlineRunListItem) => name || r.file_name || '-',
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (s: string) => {
        const cfg = runStatusConfig[s] || { color: 'default', text: s }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    {
      title: '进度', key: 'progress', width: 200,
      render: (_: unknown, r: OutlineRunListItem) => {
        if (r.status === 'done') return <Tag color="success">完成</Tag>
        if (r.status === 'partial') {
          return <Tag color="warning">成功 {r.successful_subjects}/{r.total_subjects}</Tag>
        }
        if (r.status === 'failed') return <Tag color="error">{r.error_detail?.slice(0, 50) || '失败'}</Tag>
        return (
          <Space direction="vertical" size={0} style={{ width: '100%' }}>
            <span style={{ fontSize: 12, color: '#888' }}>{r.stage_detail || r.current_stage || '处理中...'}</span>
            {r.total_subjects > 0 && (
              <Progress
                percent={Math.round((r.processed_subjects / r.total_subjects) * 100)}
                size="small"
                status="active"
                format={() => `${r.processed_subjects}/${r.total_subjects}`}
              />
            )}
          </Space>
        )
      },
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'actions', width: 160,
      render: (_: unknown, r: OutlineRunListItem) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => viewRunDetail(r)}>
            详情
          </Button>
          <Popconfirm
            title="确认删除此任务记录？"
            description="仅删除任务记录，不影响已入库的大纲数据"
            onConfirm={() => deleteRunMut.mutate(r.id)}
            okText="确认"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}
              loading={deleteRunMut.isPending && deleteRunMut.variables === r.id}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="admin-workspace outline-page">
      <PageHeader
        eyebrow="内容资产"
        title="大纲管理"
        description="管理考试大纲、章节树、考察目标和复习指导生成任务。"
        actions={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setImportModalOpen(true)}>
            导入大纲
          </Button>
        }
      />

      {/* 已入库大纲列表 */}
      <Card className="workspace-table-panel outline-page__panel" title="已入库大纲" style={{ marginBottom: 16 }}>
        <Table
          dataSource={outlines}
          columns={outlineColumns}
          rowKey="id"
          pagination={false}
          size="small"
          scroll={{ x: 820 }}
        />
      </Card>

      {/* 入库任务列表 */}
      <Card
        className="workspace-table-panel outline-page__panel"
        title="入库任务"
        extra={
          selectedRunKeys.length > 0 && (
            <Popconfirm
              title={`确认删除选中的 ${selectedRunKeys.length} 条任务记录？`}
              onConfirm={() => batchDeleteRunsMut.mutate(selectedRunKeys as string[])}
              okText="确认"
              cancelText="取消"
            >
              <Button size="small" danger loading={batchDeleteRunsMut.isPending}>
                批量删除 ({selectedRunKeys.length})
              </Button>
            </Popconfirm>
          )
        }
      >
        <Table
          dataSource={runs}
          columns={runColumns}
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ x: 900 }}
          rowSelection={{
            selectedRowKeys: selectedRunKeys,
            onChange: (keys) => setSelectedRunKeys(keys),
          }}
          locale={{ emptyText: '暂无入库任务' }}
        />
      </Card>

      {/* 导入大纲弹窗 / 查看任务详情弹窗 */}
      <Modal
        rootClassName="admin-modal outline-modal"
        title={detailRunId ? `任务详情 - ${parsedFileName}` : '导入大纲（PDF + LLM 拆分）'}
        open={importModalOpen}
        onCancel={resetImport}
        footer={null}
        width={960}
        destroyOnClose
      >
        <Space className="outline-modal__stack" direction="vertical" style={{ width: '100%' }} size="middle">
          {/* 导入模式下显示上传控件 */}
          {!detailRunId && (
            <>
              <Alert
                type="info"
                showIcon
                message="上传 408 大纲 PDF，自动拆分四门课"
                description="系统先用 MinerU 全文解析，再让 LLM 按四门课拆出考察目标 + 多层章节树（含原文考点）。复习指导在入库后单独生成。"
              />

              <Dragger
                beforeUpload={beforeUpload}
                showUploadList={false}
                accept=".pdf"
                disabled={uploadMut.isPending}
              >
                <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                <p className="ant-upload-text">点击或拖拽大纲文件到此处</p>
                <p className="ant-upload-hint">解析 + LLM 拆分较耗时，可能需要数分钟。任务启动后可在下方任务列表中查看进度。</p>
              </Dragger>
            </>
          )}

          {/* 详情模式下显示任务状态提示 */}
          {detailRunId && !splitSubjects && (
            <Alert type="info" showIcon message="该任务尚未产出拆分结果，或拆分已失败" />
          )}

          {splitSubjects && splitSubjects.length > 0 && (
            <Card className="workspace-panel outline-modal__preview" size="small" title={`拆分预览（${parsedFileName}，${splitSubjects.length} 门课）`}>
              <Tabs
                items={splitSubjects.map((s) => ({
                  key: s.subject_id,
                  label: `${s.subject_name}（${s.total_chapters}）`,
                  children: (
                    <Space direction="vertical" style={{ width: '100%' }}>
                      {s.error && (
                        <Alert
                          type="error"
                          showIcon
                          message={`${s.subject_name}拆分失败`}
                          description={s.error}
                        />
                      )}
                      {s.exam_objective && (
                        <Alert
                          type="success"
                          message="考察目标"
                          description={<Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{s.exam_objective}</Paragraph>}
                        />
                      )}
                      {!s.error && (
                        <Tree
                          treeData={buildTreeNodes(s.chapters)}
                          defaultExpandAll={s.total_chapters < 40}
                          showLine
                          height={320}
                        />
                      )}
                    </Space>
                  ),
                }))}
              />
            </Card>
          )}

          {splitSubjects && splitSubjects.length === 0 && (
            <Alert type="warning" message="LLM 未拆分出任何科目，请检查大纲内容或 outline_llm 配置" />
          )}

          {splitSubjects && splitSubjects.length > 0 && (
            <Card className="workspace-panel outline-modal__settings" size="small" title="入库设置（四门课一次入库）">
              <Form form={form} layout="vertical" onFinish={(v) => importMut.mutate(v)}>
                <div className="outline-import-form__grid">
                  <Form.Item name="name" label="大纲名称" rules={[{ required: true }]}>
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
                </div>
                <Button type="primary" htmlType="submit" loading={importMut.isPending}>确认导入</Button>
              </Form>
            </Card>
          )}
        </Space>
      </Modal>

      {/* 章节查看：按科目分 Tab，展示考察目标 + 章节树 + 复习指导生成 */}
      <Modal
        rootClassName="admin-modal outline-chapter-modal"
        title={chapterDrawer.outline ? `章节 - ${chapterDrawer.outline.name}` : '章节'}
        open={chapterDrawer.open}
        onCancel={() => { setChapterDrawer({ outline: null, open: false }); setActiveSubject('') }}
        footer={null}
        width={820}
      >
        {chapterDrawer.outline && (
          <Descriptions column={{ xs: 1, sm: 2 }} size="small" style={{ marginBottom: 16 }}>
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
                  <Space className="outline-chapter-modal__actions" wrap>
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
                    <div className="outline-chapter-modal__tree">
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
                    </div>
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
      {ch.enhanced_description && (
        <div><strong>增强描述</strong><Paragraph style={{ whiteSpace: 'pre-wrap' }}>{ch.enhanced_description}</Paragraph></div>
      )}
      {ch.keywords && ch.keywords.length > 0 && (
        <div>
          <strong>关键词</strong>
          <div style={{ marginTop: 4 }}>
            {ch.keywords.map((kw: string, i: number) => (
              <Tag key={i} color="blue" style={{ marginBottom: 4 }}>{kw}</Tag>
            ))}
          </div>
        </div>
      )}
      <div><strong>复习指导</strong><Paragraph style={{ whiteSpace: 'pre-wrap' }}>{ch.exam_guidance || '（尚未生成）'}</Paragraph></div>
    </Space>
  )
}

export default OutlineList
