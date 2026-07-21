import { useState } from 'react'
import {
  ArrowRight,
  BookOpenCheck,
  ChevronDown,
  ChevronRight,
  CircleDot,
  FileText,
  History,
  ListChecks,
  MessageCircleMore,
  Network,
  Target,
} from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { outlineSubjects } from '../data/fixtures'
import { Button, PageHeading, SectionHeading, StatusMark } from '../components/Primitives'

const stateTone = {
  学习中: 'success',
  待巩固: 'warning',
  证据不足: 'neutral',
  未学习: 'neutral',
} as const

export default function MapPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [expanded, setExpanded] = useState(['data-structure', 'computer-organization'])
  const showPoint = searchParams.get('point') === 'queue'

  const toggleSubject = (id: string) => {
    setExpanded((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]))
  }

  if (showPoint) {
    return (
      <div className="page page--wide map-page">
        <button className="back-link" onClick={() => navigate('/map')} type="button">
          <ChevronRight size={16} />
          返回学习地图
        </button>
        <PageHeading
          actions={<StatusMark tone="warning">待巩固</StatusMark>}
          description="数据结构 / 栈、队列和数组 / 栈和队列的顺序存储结构"
          eyebrow="考点详情"
          title="循环队列"
        />

        <section className="point-overview">
          <div className="point-definition">
            <p className="eyebrow">核心定义</p>
            <h2>用模运算复用顺序存储空间。</h2>
            <p>重点掌握队首、队尾、长度，以及判空和判满条件之间的下标关系。</p>
            <div className="keyword-line">
              <span>顺序队列</span>
              <span>队空判断</span>
              <span>队满判断</span>
              <span>Circular Queue</span>
            </div>
          </div>
          <div className="mastery-evidence">
            <p className="eyebrow">掌握证据</p>
            <div>
              <strong>最近 7 天作答 4 题</strong>
              <span>正确 2 题</span>
            </div>
            <div>
              <strong>同类下标题连续错误</strong>
              <span>2 次</span>
            </div>
            <div>
              <strong>提示使用</strong>
              <span>一级提示 1 次</span>
            </div>
            <small>证据只用于判断下一步内容，不换算为伪精确掌握率。</small>
          </div>
        </section>

        <section className="point-relations">
          <SectionHeading meta="按学习关系组织，不是装饰性知识图谱" title="关联结构" />
          <div className="relation-line">
            <div><span>前置</span><strong>顺序表与数组下标</strong></div>
            <ArrowRight size={18} />
            <div className="is-current"><span>当前</span><strong>循环队列</strong></div>
            <ArrowRight size={18} />
            <div><span>关联</span><strong>队空与队满判断</strong></div>
          </div>
        </section>

        <section className="point-resources">
          <div>
            <SectionHeading meta="已审核内容" title="知识与原题" />
            <button type="button">
              <span className="resource-icon"><BookOpenCheck size={18} /></span>
              <span><strong>循环队列：定义与下标关系</strong><small>平台知识 · 最近更新于 7 月 14 日</small></span>
              <ChevronRight size={17} />
            </button>
            <button type="button">
              <span className="resource-icon"><FileText size={18} /></span>
              <span><strong>试卷4.pdf · 第 1 题</strong><small>原题 · 选项经原文恢复并审核</small></span>
              <ChevronRight size={17} />
            </button>
          </div>
          <div>
            <SectionHeading meta="你的学习记录" title="错误与复习" />
            <button onClick={() => navigate('/mistakes?point=queue')} type="button">
              <span className="resource-icon resource-icon--warning"><ListChecks size={18} /></span>
              <span><strong>条件遗漏 · 3 次</strong><small>下一次复习：今天</small></span>
              <ChevronRight size={17} />
            </button>
            <button type="button">
              <span className="resource-icon"><History size={18} /></span>
              <span><strong>最近一次讲解</strong><small>front=(rear-length+1+m) MOD m</small></span>
              <ChevronRight size={17} />
            </button>
          </div>
        </section>

        <div className="point-actions">
          <Button icon={<MessageCircleMore size={17} />} onClick={() => navigate('/agent/queue?state=complete')}>
            请 Agent 讲解
          </Button>
          <Button icon={<BookOpenCheck size={17} />} onClick={() => navigate('/practice/queue-check?question=1')} tone="secondary">
            开始专项练习
          </Button>
          <Button icon={<ListChecks size={17} />} onClick={() => navigate('/mistakes?point=queue')} tone="quiet">
            查看我的错误
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="page page--wide map-page">
      <PageHeading
        actions={
          <div className="map-legend">
            <span><i className="is-learning" /> 学习中</span>
            <span><i className="is-review" /> 待巩固</span>
            <span><i className="is-unknown" /> 证据不足</span>
          </div>
        }
        description="按 408 大纲查看学习证据、待复习任务和最近活动。"
        eyebrow="学习地图"
        title="四门学科，一条可追溯的学习路径"
      />

      <section className="map-summary">
        <div>
          <span><Target size={18} /></span>
          <p>本周聚焦</p>
          <strong>3 组专项</strong>
          <small>队列、存储系统、中断</small>
        </div>
        <div>
          <span><CircleDot size={18} /></span>
          <p>正在学习</p>
          <strong>14 个考点</strong>
          <small>其中 6 个等待验证</small>
        </div>
        <div>
          <span><History size={18} /></span>
          <p>到期复习</p>
          <strong>13 个考点</strong>
          <small>今天优先处理 4 个</small>
        </div>
        <div>
          <span><Network size={18} /></span>
          <p>证据不足</p>
          <strong>8 个考点</strong>
          <small>不显示推测掌握率</small>
        </div>
      </section>

      <section className="outline-tree">
        <SectionHeading meta="展开学科查看章节状态" title="大纲进度" />
        {outlineSubjects.map((subject) => {
          const isExpanded = expanded.includes(subject.id)
          return (
            <div className="subject-block" key={subject.id}>
              <button className="subject-block__header" onClick={() => toggleSubject(subject.id)} type="button">
                <span className="subject-block__toggle">
                  <ChevronDown className={isExpanded ? 'is-open' : ''} size={18} />
                </span>
                <span className="subject-block__name">
                  <strong>{subject.name}</strong>
                  <small>{subject.progress}</small>
                </span>
                <span className="subject-block__stat"><strong>{subject.active}</strong><small>学习中</small></span>
                <span className="subject-block__stat"><strong>{subject.review}</strong><small>待复习</small></span>
                <ChevronRight size={17} />
              </button>
              {isExpanded ? (
                <div className="chapter-list">
                  {subject.chapters.map((chapter) => (
                    <button
                      key={chapter.name}
                      onClick={() => {
                        if (chapter.name === '栈、队列和数组') navigate('/map?point=queue')
                      }}
                      type="button"
                    >
                      <span className="chapter-list__line" />
                      <span className="chapter-list__node" />
                      <strong>{chapter.name}</strong>
                      <StatusMark tone={stateTone[chapter.state as keyof typeof stateTone]}>{chapter.state}</StatusMark>
                      <small>{chapter.evidence}</small>
                      <ChevronRight size={16} />
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          )
        })}
      </section>
    </div>
  )
}
