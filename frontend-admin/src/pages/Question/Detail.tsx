import { useParams, useNavigate } from 'react-router-dom'
import { Card, Tag, Button, Descriptions, Spin, Space } from 'antd'
import { ArrowLeftOutlined, EditOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getQuestionDetail, getSubjects, getChapters } from '@/api'
import EntityAssets from '@/components/EntityAssets'

const typeConfig: Record<string, { color: string; text: string }> = {
  choice: { color: 'blue', text: '选择题' },
  fill: { color: 'green', text: '填空题' },
  judge: { color: 'orange', text: '判断题' },
  short_answer: { color: 'purple', text: '简答题' },
  design: { color: 'red', text: '设计题' },
  analysis: { color: 'cyan', text: '分析题' },
}

const difficultyConfig: Record<string, { color: string; text: string }> = {
  easy: { color: 'green', text: '简单' },
  medium: { color: 'orange', text: '中等' },
  hard: { color: 'red', text: '困难' },
}

const QuestionDetail = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['question', id],
    queryFn: () => getQuestionDetail(id!),
    enabled: !!id,
  })

  const { data: subjectsData } = useQuery({
    queryKey: ['subjects'],
    queryFn: getSubjects,
  })

  const question = data?.data
  const subjects = subjectsData?.data || []
  const subject = subjects.find((s) => s.id === question?.subject_id)

  const { data: chaptersData } = useQuery({
    queryKey: ['chapters', question?.subject_id],
    queryFn: () => getChapters(question!.subject_id),
    enabled: !!question?.subject_id,
  })

  const chapters = chaptersData?.data || []
  const chapter = chapters.find((c) => c.id === question?.chapter_id)

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

  const typeInfo = typeConfig[question.type] || { color: 'default', text: question.type }
  const difficulty = difficultyConfig[question.difficulty] || { color: 'default', text: question.difficulty }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/questions')}>
            返回
          </Button>
          <h2 style={{ margin: 0 }}>题目详情</h2>
        </Space>
        <Button
          type="primary"
          icon={<EditOutlined />}
          onClick={() => navigate(`/admin/questions/${id}/edit`)}
        >
          编辑
        </Button>
      </div>

      <Card title="题目内容" style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 16 }}>
          <Space>
            <Tag color={typeInfo.color}>{typeInfo.text}</Tag>
            <Tag color={difficulty.color}>{difficulty.text}</Tag>
            {question.tags?.map((tag) => (
              <Tag key={tag}>{tag}</Tag>
            ))}
          </Space>
        </div>
        <div style={{ fontSize: 16, lineHeight: 1.8, marginBottom: 16 }}>
          {question.content}
        </div>
        {question.options && question.options.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            {question.options.map((opt, index) => {
              const optionKey = opt.key || opt.label || opt.option_label || String.fromCharCode(65 + index)
              return (
              <div key={`${optionKey}-${index}`} style={{ marginBottom: 8, paddingLeft: 16 }}>
                <strong>{optionKey}.</strong> {opt.text}
              </div>
              )
            })}
          </div>
        )}
      </Card>

      <Card title="答案与解析" style={{ marginBottom: 16 }}>
        <Descriptions bordered column={1}>
          <Descriptions.Item label="标准答案">
            <div style={{ fontWeight: 'bold', color: '#52c41a' }}>{question.answer}</div>
          </Descriptions.Item>
          {question.explanation && (
            <Descriptions.Item label="解析">
              <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
                {question.explanation}
              </div>
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      <Card title="基本信息">
        <Descriptions bordered column={2}>
          <Descriptions.Item label="学科">{subject?.name || question.subject_id}</Descriptions.Item>
          <Descriptions.Item label="章节">{chapter?.name || question.chapter_id}</Descriptions.Item>
          <Descriptions.Item label="来源">{question.source || '-'}</Descriptions.Item>
          <Descriptions.Item label="年份">{question.exam_year && question.exam_year > 0 ? question.exam_year : '-'}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={question.status === 'active' ? 'green' : 'default'}>
              {question.status === 'active' ? '已发布' : '待审核'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">{question.created_at || '-'}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title={`图片/表格/公式 (${(question as any).assets?.length || 0})`} style={{ marginTop: 16 }}>
        <EntityAssets assets={(question as any).assets || []} />
      </Card>
    </div>
  )
}

export default QuestionDetail
