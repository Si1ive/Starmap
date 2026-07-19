import {
  ArrowRight,
  BookOpenCheck,
  CalendarRange,
  Clock3,
  FileQuestion,
  ListChecks,
  RotateCcw,
  Sparkles,
  Target,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { todayTasks } from '../data/fixtures'
import { Button, PageHeading, SectionHeading, SourceBadge } from '../components/Primitives'

const practiceIcons = {
  review: RotateCcw,
  practice: BookOpenCheck,
  lesson: Sparkles,
}

const practiceRoutes = {
  'queue-review': '/practice/queue-check?question=1',
  'cache-practice': '/practice/queue-check?question=1&mode=chapter',
  'interrupt-lesson': '/agent',
} as const

const practiceEntrances = [
  {
    icon: Target,
    title: '按章节练习',
    detail: '从 408 大纲选择章节，集中完成一个考点的基础与变式题。',
    meta: '专项训练',
    route: '/practice/queue-check?question=1&mode=chapter',
  },
  {
    icon: FileQuestion,
    title: '真题演练',
    detail: '按年份和学科进入真题，保留原题来源与作答反馈。',
    meta: '历年真题',
    route: '/practice/queue-check?question=1&mode=exam',
  },
  {
    icon: CalendarRange,
    title: '全真模拟',
    detail: '按考试节奏完成跨学科模拟，统一查看时间与得分分布。',
    meta: '模拟考试',
    route: '/practice/processor?question=1&mode=mock',
  },
  {
    icon: ListChecks,
    title: '按题型练习',
    detail: '选择客观题、主观题或易混题型，针对作答方式进行训练。',
    meta: '题型训练',
    route: '/practice/processor?question=1&mode=type',
  },
]

export default function PracticeLibraryPage() {
  const navigate = useNavigate()

  return (
    <div className="page page--wide practice-library-page">
      <PageHeading
        actions={
          <Button icon={<BookOpenCheck size={17} />} onClick={() => navigate('/practice/queue-check?question=1')}>
            开始练习
          </Button>
        }
        description="Agent 会把对话中生成的任务放在这里，也可以直接进入章节专项、历年真题和模拟考试。"
        eyebrow="练习"
        title="选择今天要完成的练习"
      />

      <section className="practice-library">
        <SectionHeading
          meta="来自 Agent 对话、今日计划和最近掌握证据"
          title="Agent 为你准备"
        />
        <div className="practice-set-list">
          {todayTasks.slice(0, 3).map((task, index) => {
            const Icon = practiceIcons[task.kind]
            return (
              <button
                className={index === 0 ? 'is-priority' : ''}
                key={task.id}
                onClick={() => navigate(practiceRoutes[task.id as keyof typeof practiceRoutes])}
                type="button"
              >
                <span className="practice-set-list__index">{String(index + 1).padStart(2, '0')}</span>
                <span className={`practice-set-list__icon practice-set-list__icon--${task.kind}`}>
                  <Icon size={18} />
                </span>
                <span className="practice-set-list__copy">
                  <strong>{task.title}</strong>
                  <small>{task.subject}</small>
                  <em>{task.reason}</em>
                </span>
                <span className="practice-set-list__meta">
                  <Clock3 size={15} />
                  <strong>{task.duration} 分钟</strong>
                  <small>{index === 0 ? '建议先完成' : '可直接开始'}</small>
                </span>
                <ArrowRight size={17} />
              </button>
            )
          })}
        </div>
      </section>

      <section className="practice-entrances">
        <SectionHeading meta="题库、章节和考试模式" title="其他练习入口" />
        <div className="practice-entrance-list">
          {practiceEntrances.map((entry) => {
            const Icon = entry.icon
            return (
              <button key={entry.title} onClick={() => navigate(entry.route)} type="button">
                <span className="practice-entrance-list__icon"><Icon size={19} /></span>
                <span>
                  <strong>{entry.title}</strong>
                  <small>{entry.detail}</small>
                </span>
                <span className="practice-entrance-list__meta">
                  <SourceBadge type={entry.title === '真题演练' ? 'question' : 'outline'}>
                    {entry.meta}
                  </SourceBadge>
                  <ArrowRight size={17} />
                </span>
              </button>
            )
          })}
        </div>
      </section>
    </div>
  )
}
