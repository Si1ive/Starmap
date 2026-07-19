import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  message,
  Select,
  Space,
  Spin,
} from 'antd'
import {
  ArrowLeftOutlined,
  DeleteOutlined,
  PlusOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getCanonicalChapters,
  getQuestionDetail,
  getSubjects,
  updateQuestion,
} from '@/api'
import type { UpdateQuestionData } from '@/api/question'
import type { CanonicalChapter, Question } from '@/types'
import PageHeader from '@/components/PageHeader'

type EditableOption = {
  key?: string
  text?: string
}

interface QuestionFormValues {
  subject_id: string
  outline_chapter_id: string
  primary_chapter_id: string
  type: Question['type']
  content: string
  options?: EditableOption[]
  answer: string
  explanation?: string
  difficulty: Question['difficulty']
  source?: string
  exam_year?: number
  tags?: string[]
  status: 'active' | 'pending'
}

const findRootChapter = (
  chapters: CanonicalChapter[],
  chapterId?: string,
) => {
  if (!chapterId) return undefined
  const chapterMap = new Map(chapters.map((chapter) => [chapter.id, chapter]))
  let current = chapterMap.get(chapterId)
  const visited = new Set<string>()

  while (current?.parent_id && !visited.has(current.id)) {
    visited.add(current.id)
    current = chapterMap.get(current.parent_id)
  }
  return current
}

const belongsToRoot = (
  chapter: CanonicalChapter,
  rootId: string,
  chapterMap: Map<string, CanonicalChapter>,
) => {
  let current: CanonicalChapter | undefined = chapter
  const visited = new Set<string>()

  while (current && !visited.has(current.id)) {
    if (current.id === rootId) return true
    visited.add(current.id)
    current = current.parent_id ? chapterMap.get(current.parent_id) : undefined
  }
  return false
}

const buildChapterPath = (
  chapter: CanonicalChapter,
  chapterMap: Map<string, CanonicalChapter>,
) => {
  const names = [chapter.name]
  let parentId = chapter.parent_id
  const visited = new Set<string>([chapter.id])

  while (parentId && !visited.has(parentId)) {
    visited.add(parentId)
    const parent = chapterMap.get(parentId)
    if (!parent) break
    names.unshift(parent.name)
    parentId = parent.parent_id
  }
  return names.join(' / ')
}

const normalizeOptions = (question: Question) =>
  (question.options || []).map((option, index) => {
    const key =
      option.key ||
      option.label ||
      option.option_label ||
      String.fromCharCode(65 + index)
    return {
      ...option,
      key,
      label: option.label || key,
      option_label: option.option_label || key,
      text: option.text || '',
    }
  })

const mergeEditedOptions = (
  question: Question,
  editedOptions: EditableOption[] = [],
): NonNullable<Question['options']> => {
  const originalOptions = normalizeOptions(question)
  const originalByKey = new Map(
    originalOptions.map((option) => [option.key?.toUpperCase(), option]),
  )

  return editedOptions.map((option, index) => {
    const key = (option.key || String.fromCharCode(65 + index)).trim().toUpperCase()
    const text = option.text || ''
    const original =
      originalByKey.get(key) ||
      originalOptions[index]
    const changed =
      !original ||
      original.key?.toUpperCase() !== key ||
      original.text !== text

    return {
      ...(original || {}),
      key,
      label: key,
      option_label: key,
      text,
      source: changed ? 'manual' : original?.source,
    }
  })
}

const QuestionEdit = () => {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form] = Form.useForm<QuestionFormValues>()
  const [selectedSubject, setSelectedSubject] = useState<string>()
  const [selectedType, setSelectedType] = useState<Question['type']>('choice')
  const [selectedOutlineChapter, setSelectedOutlineChapter] = useState<string>()
  const listPath = `/admin/questions${location.search}`

  const { data, isLoading } = useQuery({
    queryKey: ['question', id],
    queryFn: () => getQuestionDetail(id || ''),
    enabled: !!id,
  })

  const { data: subjectsData } = useQuery({
    queryKey: ['subjects'],
    queryFn: getSubjects,
  })

  const { data: canonicalData, isLoading: isLoadingCanonical } = useQuery({
    queryKey: ['canonicalChapters', selectedSubject, 'flat'],
    queryFn: () => getCanonicalChapters(selectedSubject || ''),
    enabled: !!selectedSubject,
  })

  const question = data?.data
  const subjects = subjectsData?.data || []
  const canonicalChapters = useMemo(
    () => canonicalData?.data || [],
    [canonicalData?.data],
  )
  const chapterMap = useMemo(
    () => new Map(canonicalChapters.map((chapter) => [chapter.id, chapter])),
    [canonicalChapters],
  )
  const outlineChapters = useMemo(
    () =>
      canonicalChapters
        .filter(
          (chapter) =>
            chapter.status !== 'inactive' &&
            (chapter.level === 1 || !chapter.parent_id),
        )
        .sort((left, right) => left.sort_order - right.sort_order),
    [canonicalChapters],
  )
  const pointOptions = useMemo(() => {
    if (!selectedOutlineChapter) return []
    return canonicalChapters
      .filter(
        (chapter) =>
          chapter.status !== 'inactive' &&
          belongsToRoot(chapter, selectedOutlineChapter, chapterMap),
      )
      .sort((left, right) => {
        if (left.level !== right.level) return left.level - right.level
        return left.sort_order - right.sort_order
      })
      .map((chapter) => ({
        label:
          chapter.id === selectedOutlineChapter
            ? `${chapter.name}（章节）`
            : buildChapterPath(chapter, chapterMap),
        value: chapter.id,
      }))
  }, [canonicalChapters, chapterMap, selectedOutlineChapter])

  useEffect(() => {
    if (!question) return
    setSelectedSubject(question.subject_id)
    setSelectedType(question.type)
    form.setFieldsValue({
      subject_id: question.subject_id,
      primary_chapter_id: question.primary_chapter_id,
      type: question.type,
      difficulty: question.difficulty,
      status: question.status === 'deleted' ? 'pending' : question.status,
      exam_year: question.exam_year,
      source: question.source,
      tags: question.tags,
      content: question.content,
      options: normalizeOptions(question),
      answer: question.answer,
      explanation: question.explanation,
    })
  }, [form, question])

  useEffect(() => {
    if (!question?.primary_chapter_id || canonicalChapters.length === 0) return
    const root = findRootChapter(canonicalChapters, question.primary_chapter_id)
    if (!root) return
    setSelectedOutlineChapter(root.id)
    form.setFieldValue('outline_chapter_id', root.id)
  }, [canonicalChapters, form, question?.primary_chapter_id])

  const mutation = useMutation({
    mutationFn: (values: UpdateQuestionData) => {
      if (!id) throw new Error('题目 ID 缺失')
      return updateQuestion(id, values)
    },
    onSuccess: (res) => {
      const indexingStatus = res.data?.indexing?.status
      if (indexingStatus === 'failed') {
        message.warning('题目已保存，但检索索引更新失败，可稍后重试')
      } else if (indexingStatus === 'warning') {
        message.warning('题目和新索引已保存，但旧向量清理失败')
      } else {
        message.success('更新成功')
      }
      queryClient.invalidateQueries({ queryKey: ['questions'] })
      queryClient.invalidateQueries({ queryKey: ['question', id] })
      navigate(listPath)
    },
    onError: (error: any) => {
      if (error?.code === 'ECONNABORTED') {
        message.error('保存等待超时，请刷新题目确认数据后再重试')
      }
    },
  })

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (!question) return

      mutation.mutate({
        subject_id: values.subject_id,
        primary_chapter_id: values.primary_chapter_id,
        type: values.type,
        difficulty: values.difficulty,
        status: values.status,
        exam_year: values.exam_year,
        source: values.source,
        tags: values.tags,
        content: values.content,
        options:
          values.type === 'choice'
            ? mergeEditedOptions(question, values.options)
            : [],
        answer: values.answer,
        explanation: values.explanation,
      })
    } catch {
      // Ant Design 会在表单中标出未通过校验的字段。
    }
  }

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 100 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  if (!question) {
    return <div>题目不存在</div>
  }

  return (
    <div className="content-form-page question-edit-page">
      <PageHeader
        eyebrow="内容资产 / 题目"
        title="编辑题目"
        description="维护题目归属、题型、题干、标准答案与解析。"
        actions={
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(listPath)}>
              返回列表
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={mutation.isPending}
              onClick={handleSubmit}
            >
              保存
            </Button>
          </Space>
        }
      />

      <Form form={form} layout="vertical">
        <Card className="content-form-section" title="归属信息">
          <div className="content-form-grid content-form-grid--wide">
            <Form.Item
              name="subject_id"
              label="科目"
              rules={[{ required: true, message: '请选择科目' }]}
            >
              <Select
                placeholder="选择科目"
                onChange={(value) => {
                  setSelectedSubject(value)
                  setSelectedOutlineChapter(undefined)
                  form.setFieldsValue({
                    outline_chapter_id: undefined,
                    primary_chapter_id: undefined,
                  })
                }}
                options={subjects.map((subject) => ({
                  label: subject.name,
                  value: subject.id,
                }))}
              />
            </Form.Item>
            <Form.Item
              name="outline_chapter_id"
              label="大纲章节"
              rules={[{ required: true, message: '请选择大纲章节' }]}
            >
              <Select
                placeholder="选择大纲章节"
                disabled={!selectedSubject}
                loading={isLoadingCanonical}
                onChange={(value) => {
                  setSelectedOutlineChapter(value)
                  form.setFieldValue('primary_chapter_id', undefined)
                }}
                options={outlineChapters.map((chapter) => ({
                  label: chapter.name,
                  value: chapter.id,
                }))}
              />
            </Form.Item>
            <Form.Item
              name="primary_chapter_id"
              label="考点"
              rules={[{ required: true, message: '请选择考点' }]}
            >
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择考点"
                disabled={!selectedOutlineChapter}
                loading={isLoadingCanonical}
                options={pointOptions}
              />
            </Form.Item>
          </div>
        </Card>

        <Card className="content-form-section" title="题目属性">
          <div className="content-form-grid">
            <Form.Item
              name="type"
              label="题型"
              rules={[{ required: true, message: '请选择题型' }]}
            >
              <Select
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
            <Form.Item name="difficulty" label="难度">
              <Select
                options={[
                  { label: '简单', value: 'easy' },
                  { label: '中等', value: 'medium' },
                  { label: '困难', value: 'hard' },
                ]}
              />
            </Form.Item>
            <Form.Item name="status" label="可用状态">
              <Select
                options={[
                  { label: '使用中', value: 'active' },
                  { label: '已停用', value: 'pending' },
                ]}
              />
            </Form.Item>
            <Form.Item name="exam_year" label="年份">
              <InputNumber
                min={0}
                max={2100}
                precision={0}
                placeholder="如：2024"
                style={{ width: '100%' }}
              />
            </Form.Item>
          </div>
          <Form.Item name="source" label="来源">
            <Input placeholder="如：2024年408真题" />
          </Form.Item>
          <Form.Item name="tags" label="标签" style={{ marginBottom: 0 }}>
            <Select mode="tags" placeholder="输入标签后回车" />
          </Form.Item>
        </Card>

        <Card className="content-form-section" title="题目内容">
          <Form.Item
            name="content"
            label="题目"
            rules={[{ required: true, message: '请输入题目' }]}
          >
            <Input.TextArea rows={6} placeholder="题目正文" />
          </Form.Item>

          {selectedType === 'choice' && (
            <Form.List name="options">
              {(fields, { add, remove }) => (
                <>
                  {fields.map((field) => (
                    <div className="question-option-row" key={field.key}>
                      <Form.Item
                        {...field}
                        name={[field.name, 'key']}
                        rules={[{ required: true, message: '缺少标号' }]}
                      >
                        <Input placeholder="A" maxLength={2} />
                      </Form.Item>
                      <Form.Item
                        {...field}
                        name={[field.name, 'text']}
                        rules={[{ required: true, message: '请输入选项内容' }]}
                      >
                        <Input placeholder="选项内容" />
                      </Form.Item>
                      <Button
                        danger
                        type="text"
                        aria-label="删除选项"
                        title="删除选项"
                        icon={<DeleteOutlined />}
                        onClick={() => remove(field.name)}
                      />
                    </div>
                  ))}
                  <Button
                    type="dashed"
                    icon={<PlusOutlined />}
                    onClick={() =>
                      add({
                        key: String.fromCharCode(65 + fields.length),
                        text: '',
                      })
                    }
                  >
                    添加选项
                  </Button>
                </>
              )}
            </Form.List>
          )}
        </Card>

        <Card className="content-form-section" title="答案与解析">
          <Form.Item
            name="answer"
            label="标准答案"
            rules={[{ required: true, message: '请输入答案' }]}
          >
            <Input.TextArea rows={3} placeholder="标准答案" />
          </Form.Item>
          <Form.Item name="explanation" label="解析" style={{ marginBottom: 0 }}>
            <Input.TextArea rows={6} placeholder="题目解析" />
          </Form.Item>
        </Card>
      </Form>
    </div>
  )
}

export default QuestionEdit
