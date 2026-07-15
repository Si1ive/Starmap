import { ArrowRight, CalendarCheck2, Check, Clock3, Filter, History, ListChecks, RotateCcw } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { mistakeClusters } from '../data/fixtures'
import { Button, PageHeading, SectionHeading, StatusMark } from '../components/Primitives'

export default function MistakesPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const newMistake = searchParams.get('new') === 'queue'
  const confirmedReason = searchParams.get('reason') ?? '条件遗漏'

  return (
    <div className="page page--wide mistakes-page">
      <PageHeading
        actions={
          <button className="filter-control" type="button">
            <Filter size={16} />
            待复习
          </button>
        }
        description="按错误模式组织，而不是把做错的题简单堆在一起。"
        eyebrow="错题与复习"
        title="先修正稳定出现的错误路径"
      />

      {newMistake ? (
        <section className="mistake-created">
          <span><Check size={18} /></span>
          <div>
            <p className="eyebrow">已记录并安排复习</p>
            <h2>循环队列 · {confirmedReason}</h2>
            <p>首次无提示验证已加入今日队列；答对后将在 4 天后安排变式题。</p>
          </div>
          <Button icon={<ArrowRight size={16} />} onClick={() => navigate('/today')} tone="secondary">
            查看今日任务
          </Button>
        </section>
      ) : null}

      <section className="review-queue">
        <SectionHeading meta="4 个考点 · 预计 15 分钟" title="今天到期" />
        <div className="review-queue__lead">
          <span className="review-queue__index">01</span>
          <span className="review-queue__icon"><RotateCcw size={19} /></span>
          <span>
            <strong>循环队列下标计算</strong>
            <small>错误模式：条件遗漏 · 最近错误 3 次</small>
            <em>先回忆推导，再做 1 道无提示变式题</em>
          </span>
          <span><Clock3 size={15} /> 6 分钟</span>
          <Button icon={<ArrowRight size={16} />} onClick={() => navigate('/practice/queue-check?question=1')}>
            开始复习
          </Button>
        </div>
      </section>

      <section className="mistake-clusters">
        <SectionHeading meta="根据最近行为动态更新" title="错误模式" />
        <div className="mistake-cluster-list">
          {mistakeClusters.map((cluster, index) => (
            <button className={index === 0 ? 'is-active' : ''} key={cluster.title} type="button">
              <span className="mistake-cluster-list__count">{cluster.count}</span>
              <span className="mistake-cluster-list__copy">
                <span>
                  <strong>{cluster.title}</strong>
                  <StatusMark tone={index === 0 ? 'warning' : 'neutral'}>{cluster.state}</StatusMark>
                </span>
                <p>{cluster.description}</p>
                <small>{cluster.point}</small>
              </span>
              <span className="mistake-cluster-list__next">
                <History size={16} />
                <small>下一步</small>
                <strong>{cluster.next}</strong>
              </span>
              <ArrowRight size={17} />
            </button>
          ))}
        </div>
      </section>

      <section className="mistake-history">
        <SectionHeading meta="只展示会影响下一步的变化" title="本周复习轨迹" />
        <div className="history-line">
          <div>
            <span><CalendarCheck2 size={16} /></span>
            <strong>7 月 15 日</strong>
            <p>新增“循环队列 · 条件遗漏”，首次验证待完成。</p>
          </div>
          <div>
            <span><ListChecks size={16} /></span>
            <strong>7 月 14 日</strong>
            <p>“Cache 计算路径”验证通过，复习间隔延长到 4 天。</p>
          </div>
        </div>
      </section>
    </div>
  )
}
