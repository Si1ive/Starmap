import { CheckCircle2, CircleDot, Play, Route } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { ThreadPractice } from '../../api/agent'

const STATUS_COPY = {
  draft: '等待开始',
  active: '进行中',
  submitted: '已完成',
} as const

export default function ConversationPracticeRail({ items }: { items: ThreadPractice[] }) {
  const navigate = useNavigate()
  const isEmpty = items.length === 0
  return (
    <aside
      aria-hidden={isEmpty || undefined}
      aria-label="本会话练习"
      className={`agent-practice-rail${isEmpty ? ' agent-practice-rail--empty' : ''}`}
    >
      {isEmpty ? null : (
        <>
          <div className="agent-practice-rail__heading">
            <Route aria-hidden="true" size={15} />
            <div>
              <strong>本会话练习</strong>
              <small>{items.length} 份练习沿对话保留</small>
            </div>
          </div>
          <ol>
            {items.map((item) => (
              <li className={`is-${item.status}`} key={item.id}>
                <span className="agent-practice-rail__marker">
                  {item.status === 'submitted'
                    ? <CheckCircle2 aria-hidden="true" size={14} />
                    : <CircleDot aria-hidden="true" size={13} />}
                </span>
                <button
                  onClick={() => navigate(`/practice/${item.id}${item.status === 'submitted' ? '/feedback' : ''}`)}
                  type="button"
                >
                  <strong>{item.title}</strong>
                  <small>
                    {STATUS_COPY[item.status]} · {item.question_count} 道题
                    {item.status === 'submitted' ? ` · ${item.awarded_score ?? 0}/${item.total_score}` : ''}
                  </small>
                  <span><Play aria-hidden="true" size={11} />{item.status === 'submitted' ? '查看结果' : '继续练习'}</span>
                </button>
              </li>
            ))}
          </ol>
        </>
      )}
    </aside>
  )
}
