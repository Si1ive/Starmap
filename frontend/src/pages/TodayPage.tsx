import { useState } from 'react'
import {
  ArrowRight,
  BookOpenCheck,
  CalendarDays,
  Check,
  Clock3,
  Ellipsis,
  History,
  RotateCcw,
  Sparkles,
  Target,
} from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { todayTasks } from '../data/fixtures'
import { Button, EmptyState, PageHeading, ProgressBar, SectionHeading, StatusMark } from '../components/Primitives'

const taskIcons = {
  review: History,
  practice: BookOpenCheck,
  lesson: Sparkles,
}

export default function TodayPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [applied, setApplied] = useState(false)
  const isEmpty = searchParams.get('empty') === '1'
  const isPreview = searchParams.get('preview') === 'plan'

  if (isEmpty) {
    return (
      <div className="page page--narrow today-page">
        <PageHeading
          description="强化阶段 · 还没有足够的学习记录"
          eyebrow="7 月 15 日 · 星期三"
          title="今天从建立第一份计划开始"
        />
        <EmptyState
          action={
            <Button icon={<ArrowRight size={17} />} onClick={() => navigate('/onboarding')}>
              开始 10 分钟诊断
            </Button>
          }
          description="完成一组短诊断后，今日页会按考点证据安排讲解、练习与到期复习。"
          title="还没有可执行的今日任务"
        />
      </div>
    )
  }

  if (isPreview) {
    return (
      <div className="page page--wide today-page">
        <PageHeading
          actions={<StatusMark tone={applied ? 'success' : 'warning'}>{applied ? '已应用' : '等待确认'}</StatusMark>}
          description="Agent 根据死锁连续错误 3 次提出调整。原计划会保留一个可撤销版本。"
          eyebrow="计划版本 v12"
          title={applied ? '本周计划已更新' : '确认这次计划调整'}
        />

        <section className="plan-preview">
          <div className="plan-preview__header">
            <div>
              <span>影响范围</span>
              <strong>只调整周四 20 分钟</strong>
            </div>
            <div>
              <span>可撤销至</span>
              <strong>7 月 17 日 23:59</strong>
            </div>
          </div>
          <div className="plan-diff">
            <div className="plan-diff__line plan-diff__line--remove">
              <span>移除</span>
              <strong>周四 · 数据结构排序练习</strong>
              <small>20 分钟</small>
            </div>
            <div className="plan-diff__line plan-diff__line--add">
              <span>新增</span>
              <strong>周四 · 操作系统死锁专项</strong>
              <small>20 分钟</small>
            </div>
            <div className="plan-diff__line">
              <span>保持</span>
              <strong>其余 9 项任务不变</strong>
              <small>97 分钟</small>
            </div>
          </div>
          <div className="plan-preview__footer">
            {applied ? (
              <>
                <Button icon={<RotateCcw size={17} />} onClick={() => setApplied(false)} tone="secondary">
                  撤销本次调整
                </Button>
                <Button icon={<ArrowRight size={17} />} onClick={() => navigate('/today')}>
                  查看更新后的今日
                </Button>
              </>
            ) : (
              <>
                <Button onClick={() => navigate('/agent/plan?state=approval')} tone="quiet">
                  返回审批
                </Button>
                <Button icon={<Check size={17} />} onClick={() => setApplied(true)}>
                  应用这次调整
                </Button>
              </>
            )}
          </div>
        </section>
      </div>
    )
  }

  return (
    <div className="page page--wide today-page">
      <PageHeading
        actions={
          <button className="time-budget" type="button">
            <Clock3 size={17} />
            <span>
              <small>今日可用</small>
              <strong>120 分钟</strong>
            </span>
          </button>
        }
        description="强化阶段 · 本周聚焦队列、存储系统和中断"
        eyebrow="7 月 15 日 · 星期三"
        title="先把循环队列的下标关系真正弄清楚"
      />

      <section className="today-lead">
        <div className="today-lead__margin">
          <span>现在开始</span>
          <strong>01</strong>
        </div>
        <div className="today-lead__content">
          <div className="today-lead__meta">
            <span>数据结构 · 栈和队列</span>
            <StatusMark tone="warning">到期复习</StatusMark>
          </div>
          <h2>循环队列复习与 2 题验证</h2>
          <p>昨天“已知 rear 与 length 求 front”验证题答错。先用 8 分钟回忆推导，再做 2 道变式题。</p>
          <div className="today-lead__evidence">
            <span><Target size={15} /> 连续错误 2 次</span>
            <span><Clock3 size={15} /> 预计 12 分钟</span>
            <span><History size={15} /> 首次复习间隔已到</span>
          </div>
          <div className="today-lead__actions">
            <Button icon={<ArrowRight size={17} />} onClick={() => navigate('/agent/queue?state=complete')}>
              开始复习
            </Button>
            <Button onClick={() => navigate('/map?point=queue')} tone="quiet">
              查看考点证据
            </Button>
          </div>
        </div>
        <div className="today-lead__trace" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </section>

      <section className="today-queue">
        <SectionHeading meta="按推荐顺序排列 · 总计 70 分钟" title="接下来" />
        <div className="task-table">
          {todayTasks.slice(1).map((task, index) => {
            const Icon = taskIcons[task.kind]
            return (
              <div className="task-row" key={task.id}>
                <span className="task-row__order">{String(index + 2).padStart(2, '0')}</span>
                <span className={`task-row__icon task-row__icon--${task.kind}`}>
                  <Icon size={18} />
                </span>
                <span className="task-row__copy">
                  <strong>{task.title}</strong>
                  <small>{task.subject}</small>
                  <em>{task.reason}</em>
                </span>
                <span className="task-row__duration"><Clock3 size={15} /> {task.duration} 分钟</span>
                <button
                  className="task-row__action"
                  onClick={() => navigate(task.kind === 'practice' ? '/practice/queue-check?question=1' : '/agent')}
                  type="button"
                >
                  开始
                  <ArrowRight size={15} />
                </button>
                <button aria-label={`${task.title}更多操作`} className="task-row__more" title="更多操作" type="button">
                  <Ellipsis size={17} />
                </button>
              </div>
            )
          })}
        </div>
      </section>

      <section className="today-bottom">
        <div className="week-progress">
          <SectionHeading meta="目标 9 小时 30 分钟" title="本周节奏" />
          <div className="week-progress__value">
            <strong>6<small>小时</small> 42<small>分钟</small></strong>
            <span>完成 71%</span>
          </div>
          <ProgressBar label="本周学习进度" value={71} />
          <p>按当前节奏，周五可完成队列与存储系统两组专项。</p>
        </div>
        <div className="due-review">
          <SectionHeading meta="从上次离开的地方继续" title="尚未收尾" />
          <button onClick={() => navigate('/practice/processor?question=1')} type="button">
            <span className="due-review__icon"><CalendarDays size={18} /></span>
            <span>
              <strong>处理机操作序列主观题</strong>
              <small>草稿已自动保存 · 已完成第 1/2 小问</small>
            </span>
            <ArrowRight size={17} />
          </button>
        </div>
      </section>
    </div>
  )
}
