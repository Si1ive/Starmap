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
  return (
    <aside aria-label="本会话练习" className="agent-practice-rail">
      <div className="agent-practice-rail__heading">
        <Route aria-hidden="true" size={15} />
        <div>
          <strong>本会话练习</strong>
          <small>{items.length ? `${items.length} 份练习沿对话保留` : '出题后会保留在这里'}</small>
        </div>
      </div>
      {items.length ? (
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
      ) : (
        <p>让 Agent 出一道题，练习入口会和这段对话一起保存。</p>
      )}
    </aside>
  )
}
