import { useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, Check, Clock3, ShieldCheck, Sparkles } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, ProgressBar } from '../components/Primitives'

const subjects = ['数据结构', '计算机组成原理', '操作系统', '计算机网络']
const diagnosisSteps = [
  '正在读取你的目标与可用时间',
  '正在生成四科诊断题',
  '正在定位需要优先补强的考点',
]

export default function OnboardingPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const step = searchParams.get('step') ?? 'setup'
  const [minutes, setMinutes] = useState(120)
  const [selectedSubjects, setSelectedSubjects] = useState(subjects)

  const progress = useMemo(() => {
    if (step === 'diagnosis') return 58
    if (step === 'result') return 100
    return 18
  }, [step])

  const toggleSubject = (subject: string) => {
    setSelectedSubjects((current) =>
      current.includes(subject) ? current.filter((item) => item !== subject) : [...current, subject],
    )
  }

  return (
    <main className="onboarding">
      <aside className="onboarding__rail">
        <button className="onboarding__brand" onClick={() => navigate('/today')} type="button">
          <span>408</span>
          <strong>学习工作台</strong>
        </button>
        <div className="onboarding__rail-copy">
          <p className="eyebrow">首次设置</p>
          <h1>先确定边界，再让 Agent 安排学习。</h1>
          <p>用目标、时间和一组短诊断题建立第一版学习计划。之后每次调整都会留下依据。</p>
        </div>
        <div className="onboarding__trust">
          <ShieldCheck size={18} />
          <span>诊断只用于安排学习顺序，不生成虚假的精确分数。</span>
        </div>
      </aside>

      <section className="onboarding__workspace">
        <div className="onboarding__progress">
          <span>{step === 'setup' ? '设置目标' : step === 'diagnosis' ? '能力诊断' : '确认计划'}</span>
          <span>{progress}%</span>
          <ProgressBar value={progress} />
        </div>

        {step === 'setup' ? (
          <div className="onboarding-panel">
            <p className="eyebrow">01 · 学习约束</p>
            <h2>你准备怎样完成 408 强化阶段？</h2>
            <p className="onboarding-panel__lead">只收集会真正改变计划的信息，后续可随时修改。</p>

            <div className="form-section">
              <label>目标分数</label>
              <div className="score-control">
                <button type="button">100</button>
                <button className="is-selected" type="button">115</button>
                <button type="button">125+</button>
              </div>
            </div>

            <div className="form-section">
              <div className="form-section__row">
                <label htmlFor="daily-minutes">每日可用时间</label>
                <strong>{minutes} 分钟</strong>
              </div>
              <input
                id="daily-minutes"
                max="240"
                min="30"
                onChange={(event) => setMinutes(Number(event.target.value))}
                step="15"
                type="range"
                value={minutes}
              />
              <div className="range-labels">
                <span>30 分钟</span>
                <span>4 小时</span>
              </div>
            </div>

            <div className="form-section">
              <label>本阶段覆盖科目</label>
              <div className="subject-selector">
                {subjects.map((subject) => (
                  <button
                    className={selectedSubjects.includes(subject) ? 'is-selected' : ''}
                    key={subject}
                    onClick={() => toggleSubject(subject)}
                    type="button"
                  >
                    <span>{subject}</span>
                    {selectedSubjects.includes(subject) ? <Check size={16} /> : null}
                  </button>
                ))}
              </div>
            </div>

            <Button
              className="onboarding__primary"
              disabled={selectedSubjects.length === 0}
              icon={<ArrowRight size={17} />}
              onClick={() => setSearchParams({ step: 'diagnosis' })}
            >
              开始 10 分钟诊断
            </Button>
          </div>
        ) : null}

        {step === 'diagnosis' ? (
          <div className="onboarding-panel diagnosis-panel">
            <div className="diagnosis-orbit">
              <span className="diagnosis-orbit__core">58%</span>
              <span className="diagnosis-orbit__tick diagnosis-orbit__tick--one" />
              <span className="diagnosis-orbit__tick diagnosis-orbit__tick--two" />
              <span className="diagnosis-orbit__tick diagnosis-orbit__tick--three" />
            </div>
            <p className="eyebrow">02 · 正在诊断</p>
            <h2>已完成数据结构，正在检查组成原理。</h2>
            <p className="onboarding-panel__lead">当前答案会持续保存，可以稍后从同一位置继续。</p>
            <div className="diagnosis-list">
              {diagnosisSteps.map((item, index) => (
                <div className={index < 2 ? 'is-complete' : 'is-running'} key={item}>
                  <span>{index < 2 ? <Check size={15} /> : <Sparkles size={15} />}</span>
                  <strong>{item}</strong>
                  <small>{index < 2 ? '已完成' : '进行中'}</small>
                </div>
              ))}
            </div>
            <div className="onboarding__actions">
              <Button icon={<ArrowLeft size={17} />} onClick={() => setSearchParams({ step: 'setup' })} tone="quiet">
                返回设置
              </Button>
              <Button icon={<ArrowRight size={17} />} onClick={() => setSearchParams({ step: 'result' })}>
                查看诊断结果
              </Button>
            </div>
          </div>
        ) : null}

        {step === 'result' ? (
          <div className="onboarding-panel result-panel">
            <p className="eyebrow">03 · 第一版计划</p>
            <h2>先稳住队列、存储系统和中断。</h2>
            <p className="onboarding-panel__lead">计划依据来自刚才的 12 道诊断题，证据不足的考点不会被标为“已掌握”。</p>

            <div className="result-summary">
              <div>
                <span>优先巩固</span>
                <strong>3 个考点</strong>
              </div>
              <div>
                <span>每日安排</span>
                <strong>{minutes} 分钟</strong>
              </div>
              <div>
                <span>首次复盘</span>
                <strong>明天</strong>
              </div>
            </div>

            <div className="plan-lines">
              <div>
                <span className="plan-lines__index">A</span>
                <span>
                  <strong>循环队列下标关系</strong>
                  <small>先讲解 8 分钟，再用 2 道题验证</small>
                </span>
                <Clock3 size={17} />
                <em>12 分钟</em>
              </div>
              <div>
                <span className="plan-lines__index">B</span>
                <span>
                  <strong>Cache 平均访问时间</strong>
                  <small>纠正计算路径，完成一组变式题</small>
                </span>
                <Clock3 size={17} />
                <em>25 分钟</em>
              </div>
              <div>
                <span className="plan-lines__index">C</span>
                <span>
                  <strong>中断与异常辨析</strong>
                  <small>对比触发来源与响应时机</small>
                </span>
                <Clock3 size={17} />
                <em>18 分钟</em>
              </div>
            </div>

            <div className="onboarding__actions">
              <Button icon={<ArrowLeft size={17} />} onClick={() => setSearchParams({ step: 'setup' })} tone="quiet">
                调整目标
              </Button>
              <Button icon={<ArrowRight size={17} />} onClick={() => navigate('/today')}>
                采用计划并进入今日
              </Button>
            </div>
          </div>
        ) : null}
      </section>
    </main>
  )
}
