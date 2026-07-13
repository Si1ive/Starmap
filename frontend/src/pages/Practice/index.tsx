import React, { useCallback, useState, useEffect } from 'react'
import { Card, Select, Space, Typography, Tag, Button, Radio, message, Empty, Spin } from 'antd'
import { FormOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { getQuestionDetail, getQuestions, getSubjects } from '@/api/knowledge'
import type { IQuestion, ISubject } from '@/types'

const { Title, Paragraph, Text } = Typography

const typeConfig: Record<string, string> = {
  choice: '选择题',
  fill: '填空题',
  judge: '判断题',
  short_answer: '简答题',
  design: '设计题',
  analysis: '分析题',
}

const difficultyConfig: Record<string, { color: string; text: string }> = {
  easy: { color: 'green', text: '简单' },
  medium: { color: 'orange', text: '中等' },
  hard: { color: 'red', text: '困难' },
}

const PracticePage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const [subjects, setSubjects] = useState<ISubject[]>([])
  const [questions, setQuestions] = useState<IQuestion[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [selectedAnswer, setSelectedAnswer] = useState<string>('')
  const [showAnswer, setShowAnswer] = useState(false)
  const [subjectId, setSubjectId] = useState<string>('')
  const [questionType, setQuestionType] = useState<string>('choice')
  const questionId = searchParams.get('question_id')

  // Load subjects
  useEffect(() => {
    getSubjects().then((res) => {
      if (res.data) setSubjects(Array.isArray(res.data) ? res.data : [])
    })
  }, [])

  // Load questions
  const loadQuestions = useCallback(() => {
    setLoading(true)
    const request = questionId
      ? getQuestionDetail(questionId).then((res) => {
        setQuestions(res.data ? [res.data] : [])
        setCurrentIndex(0)
        setSelectedAnswer('')
        setShowAnswer(false)
      })
      : getQuestions({
        subject_id: subjectId || undefined,
        type: questionType || undefined,
        page_size: 10,
      }).then((res) => {
        if (res.data?.items) {
          setQuestions(res.data.items)
          setCurrentIndex(0)
          setSelectedAnswer('')
          setShowAnswer(false)
        }
      })

    request
      .catch(() => {
        setQuestions([])
        message.error(questionId ? '引用题目不存在或已删除' : '题目加载失败')
      })
      .finally(() => setLoading(false))
  }, [questionId, questionType, subjectId])

  useEffect(() => {
    loadQuestions()
  }, [loadQuestions])

  const currentQuestion = questions[currentIndex]

  const handleSubmit = () => {
    if (!selectedAnswer) {
      message.warning('请选择答案')
      return
    }
    setShowAnswer(true)
    if (selectedAnswer === currentQuestion.answer) {
      message.success('回答正确！')
    } else {
      message.error('回答错误')
    }
  }

  const handleNext = () => {
    if (currentIndex < questions.length - 1) {
      setCurrentIndex(currentIndex + 1)
      setSelectedAnswer('')
      setShowAnswer(false)
    } else {
      message.info('已是最后一题')
    }
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 24 }}>
      <Title level={3}>
        <FormOutlined /> 刷题练习
      </Title>

      {/* 筛选 */}
      <Card style={{ marginBottom: 16 }}>
        {questionId ? (
          <Space>
            <Tag color="blue">引用题目</Tag>
            <Button onClick={() => setSearchParams({})}>返回题库</Button>
          </Space>
        ) : (
          <Space wrap>
            <Select
              value={subjectId || 'all'}
              style={{ width: 150 }}
              onChange={(value) => setSubjectId(value === 'all' ? '' : value)}
              options={[
                { label: '全部学科', value: 'all' },
                ...subjects.map((s) => ({ label: s.name, value: s.id })),
              ]}
            />
            <Select
              value={questionType}
              style={{ width: 120 }}
              onChange={setQuestionType}
              options={[
                { label: '选择题', value: 'choice' },
                { label: '填空题', value: 'fill' },
                { label: '判断题', value: 'judge' },
                { label: '简答题', value: 'short_answer' },
              ]}
            />
            <Button onClick={loadQuestions}>换一批</Button>
          </Space>
        )}
      </Card>

      {/* 题目 */}
      <Spin spinning={loading}>
        {!currentQuestion ? (
          <Card>
            <Empty description="暂无题目，请先通过管理后台导入" />
          </Card>
        ) : (
          <Card>
            <div style={{ marginBottom: 16 }}>
              <Space>
                <Tag>{typeConfig[currentQuestion.type] || currentQuestion.type}</Tag>
                <Tag color={difficultyConfig[currentQuestion.difficulty]?.color}>
                  {difficultyConfig[currentQuestion.difficulty]?.text}
                </Tag>
                <Text type="secondary">
                  {currentIndex + 1} / {questions.length}
                </Text>
              </Space>
            </div>

            {/* 题目内容 */}
            <Paragraph style={{ fontSize: 16, lineHeight: 1.8, marginBottom: 24 }}>
              {currentQuestion.content}
            </Paragraph>

            {/* 选项（选择题） */}
            {currentQuestion.type === 'choice' && currentQuestion.options && (
              <Radio.Group
                value={selectedAnswer}
                onChange={(e) => setSelectedAnswer(e.target.value)}
                style={{ width: '100%' }}
              >
                <Space direction="vertical" style={{ width: '100%' }}>
                  {currentQuestion.options.map((opt) => (
                    <Radio
                      key={opt.key}
                      value={opt.key}
                      style={{
                        display: 'block',
                        padding: '12px 16px',
                        border: showAnswer
                          ? opt.key === currentQuestion.answer
                            ? '2px solid #52c41a'
                            : opt.key === selectedAnswer
                            ? '2px solid #ff4d4f'
                            : '1px solid #d9d9d9'
                          : '1px solid #d9d9d9',
                        borderRadius: 8,
                        marginBottom: 8,
                      }}
                    >
                      <strong>{opt.key}.</strong> {opt.text}
                      {showAnswer && opt.key === currentQuestion.answer && (
                        <CheckCircleOutlined style={{ color: '#52c41a', marginLeft: 8 }} />
                      )}
                      {showAnswer && opt.key === selectedAnswer && opt.key !== currentQuestion.answer && (
                        <CloseCircleOutlined style={{ color: '#ff4d4f', marginLeft: 8 }} />
                      )}
                    </Radio>
                  ))}
                </Space>
              </Radio.Group>
            )}

            {/* 答案和解析 */}
            {showAnswer && (
              <Card
                type="inner"
                title="答案与解析"
                style={{ marginTop: 24, background: '#f6ffed' }}
              >
                <div style={{ marginBottom: 8 }}>
                  <Text strong>正确答案：</Text>
                  <Text style={{ color: '#52c41a' }}>{currentQuestion.answer}</Text>
                </div>
                {currentQuestion.explanation && (
                  <div>
                    <Text strong>解析：</Text>
                    <Paragraph>{currentQuestion.explanation}</Paragraph>
                  </div>
                )}
              </Card>
            )}

            {/* 操作按钮 */}
            <div style={{ marginTop: 24, textAlign: 'center' }}>
              {!showAnswer ? (
                <Button type="primary" size="large" onClick={handleSubmit}>
                  提交答案
                </Button>
              ) : (
                <Button type="primary" size="large" onClick={handleNext}>
                  下一题
                </Button>
              )}
            </div>
          </Card>
        )}
      </Spin>
    </div>
  )
}

export default PracticePage
