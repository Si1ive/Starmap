import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Form, Input, Select, Button, Space, message, Spin } from 'antd'
import { ArrowLeftOutlined, SaveOutlined, PlusOutlined, MinusCircleOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getQuestionDetail, updateQuestion, getSubjects, getChapters } from '@/api'

const QuestionEdit = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [selectedSubject, setSelectedSubject] = useState<string | undefined>()
  const [selectedType, setSelectedType] = useState<string>('choice')

  const isNew = !id || id === 'new'

  const { data, isLoading } = useQuery({
    queryKey: ['question', id],
    queryFn: () => getQuestionDetail(id!),
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

  const question = data?.data
  const subjects = subjectsData?.data || []
  const chapters = chaptersData?.data || []

  const normalizedOptions = (question?.options || []).map((opt: any, index: number) => ({
    key: opt.key || opt.label || opt.option_label || String.fromCharCode(65 + index),
    text: opt.text || '',
  }))

  useEffect(() => {
    if (question) {
      setSelectedSubject(question.subject_id)
      setSelectedType(question.type)
      form.setFieldsValue({
        content: question.content,
        subject_id: question.subject_id,
        chapter_id: question.chapter_id,
        type: question.type,
        difficulty: question.difficulty,
        answer: question.answer,
        explanation: question.explanation,
        source: question.source,
        exam_year: question.exam_year,
        tags: question.tags,
        status: question.status,
        options: normalizedOptions,
      })
    }
  }, [question, form])

  const mutation = useMutation({
    mutationFn: (values: any) => updateQuestion(id!, values),
    onSuccess: () => {
      message.success('更新成功')
      queryClient.invalidateQueries({ queryKey: ['questions'] })
      queryClient.invalidateQueries({ queryKey: ['question', id] })
      navigate('/admin/questions')
    },
  })

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      mutation.mutate(values)
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
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/questions')}>
            返回
          </Button>
          <h2 style={{ margin: 0 }}>{isNew ? '新增题目' : '编辑题目'}</h2>
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
            <Form.Item name="type" label="题型" initialValue="choice" rules={[{ required: true }]}>
              <Select
                style={{ width: 120 }}
                onChange={(value) => setSelectedType(value)}
                options={[
                  { label: '选择题', value: 'choice' },
                  { label: '填空题', value: 'fill' },
                  { label: '判断题', value: 'judge' },
                  { label: '简答题', value: 'short_answer' },
                  { label: '设计题', value: 'design' },
                  { label: '分析题', value: 'analysis' },
                ]}
              />
            </Form.Item>
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
          <Space size="large">
            <Form.Item name="source" label="来源">
              <Input placeholder="如：2024年408真题" style={{ width: 200 }} />
            </Form.Item>
            <Form.Item name="exam_year" label="年份">
              <Input type="number" placeholder="如：2024" style={{ width: 120 }} />
            </Form.Item>
          </Space>
          <Form.Item name="tags" label="标签">
            <Select mode="tags" placeholder="输入标签后回车" style={{ width: '100%' }} />
          </Form.Item>
        </Card>

        <Card title="题目内容" style={{ marginBottom: 16 }}>
          <Form.Item name="content" label="题目" rules={[{ required: true, message: '请输入题目' }]}>
            <Input.TextArea rows={5} placeholder="题目正文" />
          </Form.Item>

          {selectedType === 'choice' && (
            <Form.List name="options">
              {(fields, { add, remove }) => (
                <>
                  {fields.map((field) => (
                    <Space key={field.key} align="baseline" style={{ marginBottom: 8 }}>
                      <Form.Item
                        {...field}
                        name={[field.name, 'key']}
                        rules={[{ required: true, message: '请输入选项key' }]}
                      >
                        <Input placeholder="A/B/C/D" style={{ width: 60 }} />
                      </Form.Item>
                      <Form.Item
                        {...field}
                        name={[field.name, 'text']}
                        rules={[{ required: true, message: '请输入选项内容' }]}
                      >
                        <Input placeholder="选项内容" style={{ width: 400 }} />
                      </Form.Item>
                      <MinusCircleOutlined onClick={() => remove(field.name)} />
                    </Space>
                  ))}
                  <Form.Item>
                    <Button type="dashed" onClick={() => add({ key: 'A', text: '' })} icon={<PlusOutlined />}>
                      添加选项
                    </Button>
                  </Form.Item>
                </>
              )}
            </Form.List>
          )}
        </Card>

        <Card title="答案与解析" style={{ marginBottom: 16 }}>
          <Form.Item name="answer" label="标准答案" rules={[{ required: true, message: '请输入答案' }]}>
            <Input.TextArea rows={3} placeholder="标准答案" />
          </Form.Item>
          <Form.Item name="explanation" label="解析">
            <Input.TextArea rows={5} placeholder="题目解析" />
          </Form.Item>
        </Card>
      </Form>
    </div>
  )
}

export default QuestionEdit
