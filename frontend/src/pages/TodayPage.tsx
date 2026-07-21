import { useState } from "react";
import {
  ArrowRight,
  BookOpenCheck,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clock3,
  History,
  Network,
  Play,
  Sparkles,
  Target,
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { outlineSubjects, todayTasks } from "../data/fixtures";
import {
  Button,
  EmptyState,
  PageHeading,
  SectionHeading,
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
    statusLabel: "状态稳定",
    state: "stable",
    path: "M 76 74 C 164 82, 248 108, 330 145",
    x: "33%",
    y: "33%",
    route: "/agent/deadlock?state=complete",
    reason: "已完成一次主动回忆，当前保持状态稳定。",
  },
  {
    id: "queue",
    title: "循环队列",
    subject: "数据结构",
    retention: 42,
    statusLabel: "建议巩固",
    state: "due",
    path: "M 126 72 C 274 88, 382 184, 548 310",
    x: "54.8%",
    y: "70.5%",
    route: "/agent/queue?state=complete",
    reason: "同类题连续错误 2 次，建议继续完成一次无提示回忆。",
  },
  {
    id: "cache",
    title: "Cache 访问时间",
    subject: "组成原理",
    retention: 51,
    statusLabel: "需要巩固",
    state: "due",
    path: "M 250 73 C 426 90, 548 174, 690 264",
    x: "69%",
    y: "60%",
    route: "/practice/queue-check?question=1",
    reason: "计算路径仍有跳步，需要完成一次无提示回忆。",
  },
  {
    id: "interrupt",
    title: "中断与异常",
    subject: "组成原理",
    retention: 57,
    statusLabel: "建议回顾",
    state: "due",
    path: "M 408 72 C 566 86, 700 142, 840 224",
    x: "84%",
    y: "51%",
    route: "/agent",
    reason: "近两次混淆响应时机，建议重新核对触发条件。",
  },
] as const;

const weekRhythm = [
  { day: "一", minutes: 72, height: 64, state: "done" },
  { day: "二", minutes: 96, height: 84, state: "done" },
  { day: "三", minutes: 120, height: 100, state: "done" },
  { day: "四", minutes: 0, height: 6, state: "empty" },
  { day: "五", minutes: 0, height: 6, state: "empty" },
  { day: "六", minutes: 42, height: 38, state: "today" },
  { day: "日", minutes: 0, height: 6, state: "future" },
] as const;

const outlineStateTone = {
  学习中: "success",
  待巩固: "warning",
  证据不足: "neutral",
  未学习: "neutral",
} as const;

export default function TodayPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [selectedMemoryId, setSelectedMemoryId] = useState("queue");
  const [expandedSubjects, setExpandedSubjects] = useState(
    outlineSubjects.map((subject) => subject.id),
  );
  const isEmpty = searchParams.get("empty") === "1";
  const selectedMemory =
    memoryTopics.find((topic) => topic.id === selectedMemoryId) ??
    memoryTopics[1];
  const allSubjectsExpanded =
    expandedSubjects.length === outlineSubjects.length;

  const toggleSubject = (id: string) => {
    setExpandedSubjects((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
  };

  const toggleAllSubjects = () => {
    setExpandedSubjects(
      allSubjectsExpanded ? [] : outlineSubjects.map((subject) => subject.id),
    );
  };

  if (isEmpty) {
    return (
      <div className="page page--narrow today-page">
        <PageHeading
          description="还没有足够的学习记录"
          eyebrow={currentDateLabel()}
          title="从一次对话开始"
        />
        <EmptyState
          action={
            <Button
              icon={<ArrowRight size={17} />}
              onClick={() => navigate("/agent")}
            >
              和 Agent 对话
            </Button>
          }
          description="描述你正在学习的内容或遇到的问题，系统会根据后续对话和学习记录逐步形成建议。"
          title="还没有学习记录"
        />
      </div>
    );
  }

  return (
    <div className="page today-page today-page--visual">
      <header className="today-visual-header">
        <div>
          <p>{currentDateLabel()} · 强化阶段</p>
          <h1>今天，3 个考点建议继续巩固</h1>
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
            <strong>42</strong>
            <small>分钟已记录</small>
          </span>
        </div>
      </header>

      <section className="memory-landscape" id="memory-landscape">
        <header className="memory-landscape__heading">
          <div>
            <span>记忆保持轨迹</span>
            <h2>根据已有学习证据，判断下一步是否需要巩固。</h2>
          </div>
          <div className="memory-legend" aria-label="图例">
            <span>
              <i className="memory-legend__line memory-legend__line--active" />{" "}
              当前考点
            </span>
            <span>
              <i className="memory-legend__line memory-legend__line--threshold" />{" "}
              建议巩固线
            </span>
            <span>
              <i className="memory-legend__dot" /> 学习状态
            </span>
          </div>
        </header>

        <div className="memory-chart">
          <svg
            aria-label="根据近期学习记录生成的考点记忆保持率曲线"
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
          <span className="memory-chart__threshold-label">55% · 建议巩固</span>
          <span className="memory-chart__now-label">当前状态</span>

          {memoryTopics.map((topic) => (
            <button
              aria-label={`${topic.title}，当前保持率 ${topic.retention}%，${topic.statusLabel}`}
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
                <small>{topic.statusLabel}</small>
              </span>
            </button>
          ))}

          <div className="memory-chart__dates" aria-hidden="true">
            <span>较早记录</span>
            <span>最近记录</span>
            <span>当前状态</span>
            <span>建议关注</span>
            <span>待新证据</span>
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
              {selectedMemory.subject} · {selectedMemory.statusLabel}
            </span>
            <h2>{selectedMemory.title}</h2>
            <p>{selectedMemory.reason}</p>
          </div>
          <div className="memory-focus__action">
            <span>
              <History size={15} /> 基于最近学习记录
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
            <span>建议继续巩固</span>
            <h2>根据学习证据排序，不预设具体学习时间。</h2>
          </div>
          <strong>3 个考点</strong>
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
                  <span className="today-window__time">{topic.statusLabel}</span>
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
              <strong>已记录 5 小时 30 分</strong>
            </span>
            <em>4 天</em>
          </header>
          <div className="week-rhythm__bars" aria-label="本周每日学习时长">
            {weekRhythm.map((item) => (
              <span
                className={`week-rhythm__day week-rhythm__day--${item.state}`}
                key={item.day}
              >
                <i
                  style={{ height: `${item.height}%` }}
                  title={item.minutes ? `${item.minutes} 分钟` : "尚无学习记录"}
                />
                <small>{item.day}</small>
              </span>
            ))}
          </div>
          <p>
            <Clock3 size={15} /> 学习时长只记录实际发生，不预设未来安排。
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

      <section className="progress-outline" id="outline-progress">
        <div className="progress-outline__header">
          <SectionHeading
            meta="全局学习进度与今日巩固任务统一展示"
            title="大纲进度"
          />
          <div className="map-legend">
            <span><i className="is-learning" /> 学习中</span>
            <span><i className="is-review" /> 待巩固</span>
            <span><i className="is-unknown" /> 证据不足</span>
          </div>
        </div>

        <div className="map-summary">
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
        </div>

        <div className="outline-tree">
          <div className="outline-tree__toolbar">
            <span>按学科展开大纲章节，默认显示完整目录</span>
            <button
              className="outline-toggle-all"
              onClick={toggleAllSubjects}
              type="button"
            >
              <ChevronDown className={allSubjectsExpanded ? "is-open" : ""} size={16} />
              {allSubjectsExpanded ? "收起全部" : "展开全部"}
            </button>
          </div>
          {outlineSubjects.map((subject) => {
            const isExpanded = expandedSubjects.includes(subject.id);
            return (
              <div className="subject-block" key={subject.id}>
                <button
                  className="subject-block__header"
                  onClick={() => toggleSubject(subject.id)}
                  type="button"
                >
                  <span className="subject-block__toggle">
                    <ChevronDown className={isExpanded ? "is-open" : ""} size={18} />
                  </span>
                  <span className="subject-block__name">
                    <strong>{subject.name}</strong>
                    <small>{subject.chapters.length} 个章节 · {subject.progress}</small>
                  </span>
                  <span className="subject-block__stat">
                    <strong>{subject.active}</strong>
                    <small>学习中</small>
                  </span>
                  <span className="subject-block__stat">
                    <strong>{subject.review}</strong>
                    <small>待复习</small>
                  </span>
                  <ChevronRight size={17} />
                </button>
                {isExpanded ? (
                  <div className="chapter-list">
                    {subject.chapters.map((chapter) => (
                      <button
                        key={chapter.name}
                        onClick={() => {
                          if (chapter.name === "栈、队列和数组") {
                            setSelectedMemoryId("queue");
                            document
                              .getElementById("memory-landscape")
                              ?.scrollIntoView({ behavior: "smooth", block: "start" });
                          }
                        }}
                        type="button"
                      >
                        <span className="chapter-list__line" />
                        <span className="chapter-list__node" />
                        <strong>{chapter.name}</strong>
                        <StatusMark
                          tone={
                            outlineStateTone[
                              chapter.state as keyof typeof outlineStateTone
                            ]
                          }
                        >
                          {chapter.state}
                        </StatusMark>
                        <small>{chapter.evidence}</small>
                        <ChevronRight size={16} />
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function currentDateLabel() {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date());
}
