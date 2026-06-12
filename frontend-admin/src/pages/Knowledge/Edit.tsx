import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Form, Input, Select, Button, Space, message, Spin } from 'antd'
import { ArrowLeftOutlined, SaveOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getKnowledgePointDetail, updateKnowledgePoint, getSubjects, getChapters } from '@/api'

const KnowledgeEdit = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [selectedSubject, setSelectedSubject] = useState<string | undefined>()

  const isNew = !id || id === 'new'

  const { data, isLoading } = useQuery({
    queryKey: ['knowledgePoint', id],
    queryFn: () => getKnowledgePointDetail(id!),
    enabled: !!id && !isNew,
  })

  const { data: subjectsData } = useQuery({
    queryKey: ['subjects'],
    queryFn: getSubjects,
  })

  const { data: chaptersData } = useQuery({
    queryKey: ['chapters', selectedSubject],
    queryFn: () => getChapters(selectedSubject!),
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
    }
  }, [point, form])

  const mutation = useMutation({
    mutationFn: (values: any) => updateKnowledgePoint(id!, values),
    onSuccess: () => {
      message.success('更新成功')
      queryClient.invalidateQueries({ queryKey: ['knowledgePoints'] })
      queryClient.invalidateQueries({ queryKey: ['knowledgePoint', id] })
      navigate('/admin/knowledge')
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
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/knowledge')}>
            返回
          </Button>
          <h2 style={{ margin: 0 }}>{isNew ? '新增知识点' : '编辑知识点'}</h2>
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

      <Form form={form} layout="vertical">
        <Card title="基本信息" style={{ marginBottom: 16 }}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="知识点标题" />
          </Form.Item>
          <Form.Item name="subject_id" label="学科" rules={[{ required: true, message: '请选择学科' }]}>
            <Select
              placeholder="选择学科"
              onChange={(value) => {
                setSelectedSubject(value)
                form.setFieldValue('chapter_id', undefined)
              }}
              options={subjects.map((s) => ({ label: s.name, value: s.id }))}
            />
          </Form.Item>
          <Form.Item name="chapter_id" label="章节" rules={[{ required: true, message: '请选择章节' }]}>
            <Select
              placeholder="选择章节"
              disabled={!selectedSubject}
              options={chapters.map((c) => ({ label: c.name, value: c.id }))}
            />
          </Form.Item>
          <Space size="large">
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
            <Form.Item name="exam_frequency" label="考频" initialValue="medium">
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
            <Form.Item name="status" label="状态" initialValue="active">
              <Select
                style={{ width: 120 }}
                options={[
                  { label: '已发布', value: 'active' },
                  { label: '待审核', value: 'pending' },
                ]}
              />
            </Form.Item>
          </Space>
          <Form.Item name="tags" label="标签">
            <Select
              mode="tags"
              placeholder="输入标签后回车"
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Card>

        <Card title="知识点内容" style={{ marginBottom: 16 }}>
          <Form.Item name="content" label="内容" rules={[{ required: true, message: '请输入内容' }]}>
            <Input.TextArea rows={15} placeholder="知识点正文（支持Markdown）" />
          </Form.Item>
          <Form.Item name="key_points" label="要点（每行一个）">
            <Input.TextArea rows={5} placeholder="输入要点，每行一个" />
          </Form.Item>
        </Card>
      </Form>
    </div>
  )
}

export default KnowledgeEdit
