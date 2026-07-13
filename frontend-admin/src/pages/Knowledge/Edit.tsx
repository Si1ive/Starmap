import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Form, Input, Select, Button, Space, message, Spin, Tabs, Tag, Modal } from 'antd'
import { ArrowLeftOutlined, SaveOutlined, EyeOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getKnowledgePointDetail, updateKnowledgePoint, getSubjects, getChapters } from '@/api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const KnowledgeEdit = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [selectedSubject, setSelectedSubject] = useState<string | undefined>()
  const [previewContent, setPreviewContent] = useState('')
  const [isFormDirty, setIsFormDirty] = useState(false)

  // 监听内容变化，用于实时预览
  const watchContent = Form.useWatch('content', form)

  // 监听表单变化
  const handleFormChange = () => {
    setIsFormDirty(true)
  }

  // 返回前确认
  const handleBack = () => {
    if (isFormDirty) {
      Modal.confirm({
        title: '确认离开？',
        icon: <ExclamationCircleOutlined />,
        content: '当前有未保存的修改，确定要离开吗？',
        okText: '离开',
        okType: 'danger',
        cancelText: '取消',
        onOk: () => navigate('/admin/knowledge'),
      })
    } else {
      navigate('/admin/knowledge')
    }
  }

  const { data, isLoading } = useQuery({
    queryKey: ['knowledgePoint', id],
    queryFn: () => getKnowledgePointDetail(id || ''),
    enabled: !!id,
  })

  const { data: subjectsData } = useQuery({
    queryKey: ['subjects'],
    queryFn: getSubjects,
  })

  const { data: chaptersData } = useQuery({
    queryKey: ['chapters', selectedSubject],
    queryFn: () => getChapters(selectedSubject || ''),
    enabled: !!selectedSubject,
  })

  const point = data?.data
  const subjects = subjectsData?.data || []
  const chapters = chaptersData?.data || []

  useEffect(() => {
    if (point) {
      setSelectedSubject(point.subject_id)
      form.setFieldsValue({
        title: point.title,
        content: point.content,
        subject_id: point.subject_id,
        chapter_id: point.chapter_id,
        difficulty: point.difficulty,
        exam_frequency: point.exam_frequency,
        tags: point.tags,
        key_points: point.key_points?.join('\n'),
        status: point.status,
      })
      setPreviewContent(point.content || '')
    }
  }, [point, form])

  useEffect(() => {
    if (watchContent) {
      setPreviewContent(watchContent)
    }
  }, [watchContent])

  const mutation = useMutation({
    mutationFn: (values: any) => {
      if (!id) throw new Error('知识点 ID 缺失')
      return updateKnowledgePoint(id, values)
    },
    onSuccess: (res) => {
      const indexingStatus = res.data?.indexing?.status
      if (indexingStatus === 'failed') {
        message.warning('内容已保存，但检索索引更新失败，可稍后重试')
      } else if (indexingStatus === 'warning') {
        message.warning('内容和新索引已保存，但旧向量清理失败')
      } else {
        message.success('保存成功')
      }
      setIsFormDirty(false)
      queryClient.invalidateQueries({ queryKey: ['knowledgePoints'] })
      queryClient.invalidateQueries({ queryKey: ['knowledgePoint', id] })
      navigate('/admin/knowledge')
    },
    onError: (error: any) => {
      message.error(error?.message || '保存失败，请重试')
    },
  })

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      const keyPoints = values.key_points
        ? values.key_points.split('\n').filter((s: string) => s.trim())
        : []
      mutation.mutate({ ...values, key_points: keyPoints })
    })
  }

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={handleBack}>
            返回
          </Button>
          <h2 style={{ margin: 0 }}>编辑知识点</h2>
          {isFormDirty && (
            <Tag color="orange">未保存</Tag>
          )}
        </Space>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={mutation.isPending}
          onClick={handleSubmit}
        >
          保存
        </Button>
      </div>

      <Form form={form} layout="vertical" onValuesChange={handleFormChange}>
        <Card title="基本信息" style={{ marginBottom: 16 }}>
          <Form.Item
            name="title"
            label="标题"
            rules={[
              { required: true, message: '请输入标题' },
              { min: 3, max: 200, message: '标题长度应在3-200字符之间' },
            ]}
          >
            <Input placeholder="例如：数据结构-栈的基本概念" maxLength={200} showCount />
          </Form.Item>
          <Form.Item
            name="subject_id"
            label="学科"
            rules={[{ required: true, message: '请选择学科' }]}
          >
            <Select
              placeholder="选择学科"
              onChange={(value) => {
                setSelectedSubject(value)
                form.setFieldValue('chapter_id', undefined)
              }}
              options={subjects.map((s) => ({ label: s.name, value: s.id }))}
            />
          </Form.Item>
          <Form.Item
            name="chapter_id"
            label="章节"
            rules={[{ required: true, message: '请选择章节' }]}
          >
            <Select
              placeholder={selectedSubject ? '选择章节' : '请先选择学科'}
              disabled={!selectedSubject}
              options={chapters.map((c) => ({ label: c.name, value: c.id }))}
            />
          </Form.Item>
          <Space size="large" style={{ width: '100%' }} wrap>
            <Form.Item name="difficulty" label="难度" initialValue="medium">
              <Select
                style={{ width: 120 }}
                options={[
                  { label: '简单', value: 'easy' },
                  { label: '中等', value: 'medium' },
                  { label: '困难', value: 'hard' },
                ]}
              />
            </Form.Item>
            <Form.Item name="exam_frequency" label="考试频率" initialValue="medium">
              <Select
                style={{ width: 120 }}
                options={[
                  { label: '高频', value: 'high' },
                  { label: '中频', value: 'medium' },
                  { label: '低频', value: 'low' },
                  { label: '未考', value: 'never' },
                ]}
              />
            </Form.Item>
            <Form.Item name="status" label="可用状态" initialValue="active">
              <Select
                style={{ width: 120 }}
                options={[
                  { label: '可用', value: 'active' },
                  { label: '停用', value: 'pending' },
                ]}
              />
            </Form.Item>
          </Space>
          <Form.Item
            name="tags"
            label="标签"
            tooltip="添加相关标签，便于分类和搜索"
          >
            <Select
              mode="tags"
              placeholder="输入标签后按回车，例如：核心概念、必考知识点"
              style={{ width: '100%' }}
              maxTagCount="responsive"
            />
          </Form.Item>
        </Card>

        <Card title="知识点内容" style={{ marginBottom: 16 }}>
          <Tabs
            defaultActiveKey="edit"
            items={[
              {
                key: 'edit',
                label: '编辑',
                children: (
                  <>
                    <Form.Item
                      name="content"
                      label="内容"
                      rules={[{ required: true, message: '请输入内容' }]}
                    >
                      <Input.TextArea
                        rows={15}
                        placeholder="知识点正文（支持Markdown格式）&#10;&#10;示例：&#10;## 标题&#10;### 小标题&#10;- 列表项&#10;**粗体** *斜体*&#10;```代码块```"
                        style={{ fontFamily: 'monospace' }}
                      />
                    </Form.Item>
                    <Form.Item name="key_points" label="核心要点（每行一个）">
                      <Input.TextArea
                        rows={6}
                        placeholder="每行输入一个要点，例如：&#10;理解基本概念&#10;掌握应用场景&#10;注意常见错误"
                      />
                    </Form.Item>
                  </>
                ),
              },
              {
                key: 'preview',
                label: (
                  <span>
                    <EyeOutlined /> 预览
                  </span>
                ),
                children: (
                  <div
                    style={{
                      minHeight: 400,
                      padding: 16,
                      background: '#fafafa',
                      borderRadius: 4,
                    }}
                  >
                    <div className="markdown-content">
                      {previewContent ? (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {previewContent}
                        </ReactMarkdown>
                      ) : (
                        <div style={{ color: '#999', textAlign: 'center', padding: 40 }}>
                          暂无内容
                        </div>
                      )}
                    </div>
                  </div>
                ),
              },
            ]}
          />
        </Card>
      </Form>
    </div>
  )
}

export default KnowledgeEdit
