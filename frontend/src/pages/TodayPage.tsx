import { useState } from "react";
import {
  ArrowRight,
  BookOpenCheck,
  CalendarDays,
  Check,
  Clock3,
  History,
  Play,
  RotateCcw,
  Sparkles,
  Target,
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { todayTasks } from "../data/fixtures";
import {
  Button,
  EmptyState,
  PageHeading,
  StatusMark,
} from "../components/Primitives";

const taskIcons = {
  review: History,
  practice: BookOpenCheck,
  lesson: Sparkles,
};

const memoryTopics = [
  {
    id: "deadlock",
    title: "死锁必要条件",
    subject: "操作系统",
    retention: 78,
    due: "周五 19:30",
    state: "stable",
    path: "M 76 74 C 164 82, 248 108, 330 145",
    x: "33%",
    y: "33%",
    route: "/agent/plan?state=approval",
    reason: "昨天已完成一次主动回忆，下一次复习间隔已经延长。",
  },
  {
    id: "queue",
    title: "循环队列",
    subject: "数据结构",
    retention: 42,
    due: "现在",
    state: "due",
    path: "M 126 72 C 274 88, 382 184, 548 310",
    x: "54.8%",
    y: "70.5%",
    route: "/agent/queue?state=complete",
    reason: "昨天同类题连续错误 2 次，首次回忆窗口已经打开。",
  },
  {
    id: "cache",
    title: "Cache 访问时间",
    subject: "组成原理",
    retention: 51,
    due: "10:30",
    state: "due",
    path: "M 250 73 C 426 90, 548 174, 690 264",
    x: "69%",
    y: "60%",
    route: "/practice/queue-check?question=1",
    reason: "计算路径仍有跳步，今天需要完成一次无提示回忆。",
  },
  {
    id: "interrupt",
    title: "中断与异常",
    subject: "组成原理",
    retention: 57,
    due: "16:40",
    state: "due",
    path: "M 408 72 C 566 86, 700 142, 840 224",
    x: "84%",
    y: "51%",
    route: "/agent",
    reason: "近两次混淆响应时机，傍晚将进入建议复习区。",
  },
] as const;

const weekRhythm = [
  { day: "一", minutes: 72, height: 64, state: "done" },
  { day: "二", minutes: 96, height: 84, state: "done" },
  { day: "三", minutes: 120, height: 100, state: "today" },
  { day: "四", minutes: 80, height: 70, state: "future" },
  { day: "五", minutes: 108, height: 90, state: "future" },
  { day: "六", minutes: 45, height: 42, state: "future" },
  { day: "日", minutes: 50, height: 46, state: "future" },
] as const;

export default function TodayPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [applied, setApplied] = useState(false);
  const [selectedMemoryId, setSelectedMemoryId] = useState("queue");
  const isEmpty = searchParams.get("empty") === "1";
  const isPreview = searchParams.get("preview") === "plan";
  const selectedMemory =
    memoryTopics.find((topic) => topic.id === selectedMemoryId) ??
    memoryTopics[1];

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
            <Button
              icon={<ArrowRight size={17} />}
              onClick={() => navigate("/onboarding")}
            >
              开始 10 分钟诊断
            </Button>
          }
          description="完成一组短诊断后，今日页会按考点证据安排讲解、练习与到期复习。"
          title="还没有可执行的今日任务"
        />
      </div>
    );
  }

  if (isPreview) {
    return (
      <div className="page page--wide today-page">
        <PageHeading
          actions={
            <StatusMark tone={applied ? "success" : "warning"}>
              {applied ? "已应用" : "等待确认"}
            </StatusMark>
          }
          description="Agent 根据死锁连续错误 3 次提出调整。原计划会保留一个可撤销版本。"
          eyebrow="计划版本 v12"
          title={applied ? "本周计划已更新" : "确认这次计划调整"}
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
                <Button
                  icon={<RotateCcw size={17} />}
                  onClick={() => setApplied(false)}
                  tone="secondary"
                >
                  撤销本次调整
                </Button>
                <Button
                  icon={<ArrowRight size={17} />}
                  onClick={() => navigate("/today")}
                >
                  查看更新后的今日
                </Button>
              </>
            ) : (
              <>
                <Button
                  onClick={() => navigate("/agent/plan?state=approval")}
                  tone="quiet"
                >
                  返回审批
                </Button>
                <Button
                  icon={<Check size={17} />}
                  onClick={() => setApplied(true)}
                >
                  应用这次调整
                </Button>
              </>
            )}
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page today-page today-page--visual">
      <header className="today-visual-header">
        <div>
          <p>7 月 15 日 · 星期三 · 强化阶段</p>
          <h1>今天，3 个记忆窗口正在打开</h1>
        </div>
        <div className="today-visual-snapshot" aria-label="今日学习概览">
          <span>
            <strong>12</strong>
            <small>在学考点</small>
          </span>
          <span>
            <strong>3</strong>
            <small>今日到期</small>
          </span>
          <span className="today-visual-snapshot__time">
            <Clock3 size={16} />
            <strong>120</strong>
            <small>分钟可用</small>
          </span>
        </div>
      </header>

      <section className="memory-landscape">
        <header className="memory-landscape__heading">
          <div>
            <span>记忆保持轨迹</span>
            <h2>在曲线越过临界线前，把它重新想起来。</h2>
          </div>
          <div className="memory-legend" aria-label="图例">
            <span>
              <i className="memory-legend__line memory-legend__line--active" />{" "}
              当前考点
            </span>
            <span>
              <i className="memory-legend__line memory-legend__line--threshold" />{" "}
              建议复习线
            </span>
            <span>
              <i className="memory-legend__dot" /> 下一窗口
            </span>
          </div>
        </header>

        <div className="memory-chart">
          <svg
            aria-label="过去七天到未来三天的考点记忆保持率曲线"
            preserveAspectRatio="none"
            role="img"
            viewBox="0 0 1000 440"
          >
            <rect
              className="memory-chart__review-zone"
              height="118"
              width="1000"
              x="0"
              y="270"
            />
            <g className="memory-chart__grid">
              <line x1="0" x2="1000" y1="72" y2="72" />
              <line x1="0" x2="1000" y1="170" y2="170" />
              <line x1="0" x2="1000" y1="270" y2="270" />
              <line x1="0" x2="1000" y1="388" y2="388" />
              <line x1="78" x2="78" y1="45" y2="388" />
              <line x1="300" x2="300" y1="45" y2="388" />
              <line x1="566" x2="566" y1="45" y2="388" />
              <line x1="784" x2="784" y1="45" y2="388" />
              <line x1="936" x2="936" y1="45" y2="388" />
            </g>
            <line
              className="memory-chart__threshold"
              x1="0"
              x2="1000"
              y1="270"
              y2="270"
            />
            <line
              className="memory-chart__now"
              x1="566"
              x2="566"
              y1="34"
              y2="388"
            />
            {memoryTopics.map((topic) => (
              <path
                className={`memory-path memory-path--${topic.id} ${
                  selectedMemory.id === topic.id ? "is-selected" : ""
                }`}
                d={topic.path}
                key={topic.id}
              />
            ))}
          </svg>

          <span className="memory-chart__axis memory-chart__axis--clear">
            清晰
          </span>
          <span className="memory-chart__axis memory-chart__axis--fading">
            模糊
          </span>
          <span className="memory-chart__axis memory-chart__axis--critical">
            临界
          </span>
          <span className="memory-chart__threshold-label">55% · 建议复习</span>
          <span className="memory-chart__now-label">现在</span>

          {memoryTopics.map((topic) => (
            <button
              aria-label={`${topic.title}，当前保持率 ${topic.retention}%，复习时间 ${topic.due}`}
              aria-pressed={selectedMemory.id === topic.id}
              className={`memory-node memory-node--${topic.id} ${
                selectedMemory.id === topic.id ? "is-selected" : ""
              }`}
              key={topic.id}
              onClick={() => setSelectedMemoryId(topic.id)}
              style={{ left: topic.x, top: topic.y }}
              type="button"
            >
              <span className="memory-node__dot" />
              <span className="memory-node__label">
                <strong>{topic.title}</strong>
                <small>{topic.due}</small>
              </span>
            </button>
          ))}

          <div className="memory-chart__dates" aria-hidden="true">
            <span>7 月 11 日</span>
            <span>7 月 13 日</span>
            <span>今天</span>
            <span>明天</span>
            <span>周六</span>
          </div>
        </div>

        <footer className="memory-focus">
          <div className="memory-focus__retention">
            <strong>{selectedMemory.retention}</strong>
            <span>%</span>
            <small>当前保持率</small>
          </div>
          <div className="memory-focus__copy">
            <span>
              {selectedMemory.subject} ·{" "}
              {selectedMemory.due === "现在"
                ? "窗口已打开"
                : `建议 ${selectedMemory.due} 复习`}
            </span>
            <h2>{selectedMemory.title}</h2>
            <p>{selectedMemory.reason}</p>
          </div>
          <div className="memory-focus__action">
            <span>
              <Clock3 size={15} /> 预计{" "}
              {selectedMemory.id === "cache"
                ? 25
                : selectedMemory.id === "interrupt"
                  ? 18
                  : 12}{" "}
              分钟
            </span>
            <Button
              icon={<Play size={16} />}
              onClick={() => navigate(selectedMemory.route)}
            >
              {selectedMemory.state === "stable" ? "查看学习记录" : "开始复习"}
            </Button>
          </div>
        </footer>
      </section>

      <section className="today-windows">
        <header>
          <div>
            <span>今日复习窗口</span>
            <h2>顺着记忆下降的速度安排，而不是堆满待办。</h2>
          </div>
          <strong>55 分钟</strong>
        </header>
        <div className="today-window-list">
          {memoryTopics
            .filter((topic) => topic.state === "due")
            .map((topic, index) => {
              const task = todayTasks[index];
              const Icon = taskIcons[task.kind];
              return (
                <button
                  className={
                    selectedMemory.id === topic.id ? "is-selected" : ""
                  }
                  key={topic.id}
                  onClick={() => setSelectedMemoryId(topic.id)}
                  type="button"
                >
                  <span className="today-window__time">{topic.due}</span>
                  <span
                    className={`today-window__icon today-window__icon--${topic.id}`}
                  >
                    <Icon size={17} />
                  </span>
                  <span className="today-window__copy">
                    <strong>{topic.title}</strong>
                    <small>
                      {topic.subject} · 保持率 {topic.retention}%
                    </small>
                  </span>
                  <span className="today-window__signal">
                    <i style={{ height: `${100 - topic.retention}%` }} />
                  </span>
                  <ArrowRight size={16} />
                </button>
              );
            })}
        </div>
      </section>

      <section className="today-visual-footer">
        <div className="week-rhythm">
          <header>
            <span>
              <small>本周节奏</small>
              <strong>6 小时 42 分</strong>
            </span>
            <em>71%</em>
          </header>
          <div className="week-rhythm__bars" aria-label="本周每日学习时长">
            {weekRhythm.map((item) => (
              <span
                className={`week-rhythm__day week-rhythm__day--${item.state}`}
                key={item.day}
              >
                <i
                  style={{ height: `${item.height}%` }}
                  title={`${item.minutes} 分钟`}
                />
                <small>{item.day}</small>
              </span>
            ))}
          </div>
          <p>
            <Target size={15} /> 按当前节奏，周五可完成队列与存储系统两组专项。
          </p>
        </div>

        <button
          className="today-resume"
          onClick={() => navigate("/practice/processor?question=1")}
          type="button"
        >
          <span className="today-resume__visual">
            <CalendarDays size={22} />
            <i>1/2</i>
          </span>
          <span>
            <small>尚未收尾 · 草稿已保存</small>
            <strong>处理机操作序列主观题</strong>
            <em>继续第 2 小问</em>
          </span>
          <ArrowRight size={18} />
        </button>
      </section>
    </div>
  );
}
