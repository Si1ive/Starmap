import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BookOpenCheck,
  Clock3,
  History,
  RefreshCw,
  Target,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { getLearningProgress } from "../api/learning";
import type { LearningProgress, LearningTopic } from "../api/learning";
import {
  Button,
  EmptyState,
  PageHeading,
  SectionHeading,
  SourceBadge,
} from "../components/Primitives";

function formatDuration(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours} 小时 ${minutes} 分` : `${minutes} 分钟`;
}

function curvePath(topic: LearningTopic) {
  const maxDay = Math.max(...topic.curve.map((point) => point.day), 1);
  return topic.curve
    .map((point, index) => {
      const x = 54 + (point.day / maxDay) * 842;
      const y = 34 + ((100 - point.retention) / 100) * 244;
      return `${index ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

export default function TodayPage() {
  const navigate = useNavigate();
  const [progress, setProgress] = useState<LearningProgress | null>(null);
  const [selectedKeyword, setSelectedKeyword] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const next = await getLearningProgress();
      setProgress(next);
      setSelectedKeyword(
        (current) => current || next.topics[0]?.keyword || null,
      );
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "学习进度加载失败",
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const selected = useMemo(
    () =>
      progress?.topics.find((topic) => topic.keyword === selectedKeyword) ??
      progress?.topics[0] ??
      null,
    [progress, selectedKeyword],
  );
  const weekMax = Math.max(
    ...(progress?.week.map((item) => item.study_seconds) ?? [1]),
    1,
  );

  if (!loading && progress && !progress.topics.length) {
    return (
      <div className="page page--narrow">
        <PageHeading
          description="曲线只从真实作答和知识点评分证据生成"
          eyebrow="学习进度"
          title="还没有可计算的记忆轨迹"
        />
        <EmptyState
          action={
            <Button
              icon={<ArrowRight size={17} />}
              onClick={() => navigate("/practice")}
            >
              开始真实练习
            </Button>
          }
          description="完成一次已入库真题练习或在 Agent 中完成一次知识点验证后，这里会按关键词合并证据并生成艾宾浩斯曲线。"
          title="先留下第一条学习证据"
        />
      </div>
    );
  }

  return (
    <div className="page page--wide learning-progress-real">
      <PageHeading
        actions={
          <Button
            icon={<RefreshCw className={loading ? "spin" : ""} size={16} />}
            onClick={() => void load()}
            tone="secondary"
          >
            刷新证据
          </Button>
        }
        description="知识点和题目不分两套进度：命中相同关键词的真实证据会进入同一条记忆轨迹。"
        eyebrow="学习进度"
        title="由真实学习证据生成的艾宾浩斯曲线"
      />
      {error ? <div className="practice-alert">{error}</div> : null}

      <section className="learning-summary">
        <div>
          <Target size={18} />
          <span>已学习关键词</span>
          <strong>{progress?.summary.learned_keywords ?? 0}</strong>
          <small>题目与知识点合并去重</small>
        </div>
        <div>
          <History size={18} />
          <span>建议复习</span>
          <strong>{progress?.summary.due_keywords ?? 0}</strong>
          <small>当前保持率低于 55%</small>
        </div>
        <div>
          <BookOpenCheck size={18} />
          <span>真实作答</span>
          <strong>{progress?.summary.answered_questions ?? 0}</strong>
          <small>正确率 {progress?.summary.accuracy_rate ?? 0}%</small>
        </div>
        <div>
          <Clock3 size={18} />
          <span>记录时长</span>
          <strong>
            {formatDuration(progress?.summary.study_seconds ?? 0)}
          </strong>
          <small>模拟考与完成的专注计时</small>
        </div>
      </section>

      {selected ? (
        <section className="retention-workbench">
          <header>
            <div>
              <span className="eyebrow">当前记忆轨迹</span>
              <h2>{selected.keyword}</h2>
              <p>
                {selected.evidence_count} 条真实证据 · 记忆强度{" "}
                {selected.strength_hours.toFixed(1)} 小时
              </p>
            </div>
            <div
              className={`retention-score retention-score--${selected.status}`}
            >
              <strong>{selected.retention}</strong>
              <span>%</span>
              <small>
                {selected.status === "due" ? "建议复习" : "状态稳定"}
              </small>
            </div>
          </header>
          <div className="retention-chart">
            <svg
              aria-label={`${selected.keyword}未来 30 天艾宾浩斯保持率`}
              preserveAspectRatio="none"
              role="img"
              viewBox="0 0 950 320"
            >
              <g className="retention-grid">
                <line x1="54" x2="896" y1="34" y2="34" />
                <line x1="54" x2="896" y1="144" y2="144" />
                <line x1="54" x2="896" y1="278" y2="278" />
              </g>
              <line
                className="retention-threshold"
                x1="54"
                x2="896"
                y1="143.8"
                y2="143.8"
              />
              <path className="retention-path" d={curvePath(selected)} />
              {selected.curve.map((point) => {
                const maxDay = Math.max(
                  ...selected.curve.map((item) => item.day),
                  1,
                );
                const x = 54 + (point.day / maxDay) * 842;
                const y = 34 + ((100 - point.retention) / 100) * 244;
                return (
                  <circle
                    className="retention-point"
                    cx={x}
                    cy={y}
                    key={point.day}
                    r="4"
                  />
                );
              })}
            </svg>
            <span className="retention-axis retention-axis--top">100%</span>
            <span className="retention-axis retention-axis--threshold">
              55%
            </span>
            <span className="retention-axis retention-axis--bottom">0%</span>
            <div className="retention-days">
              {selected.curve.map((point) => (
                <span key={point.day}>
                  {point.day === 0 ? "现在" : `${point.day} 天`}
                </span>
              ))}
            </div>
          </div>
          <footer>
            <div>
              <span>最近学习</span>
              <strong>
                {new Date(selected.last_studied_at).toLocaleString("zh-CN")}
              </strong>
            </div>
            <div>
              <span>建议复习时间</span>
              <strong>
                {new Date(selected.next_review_at).toLocaleString("zh-CN")}
              </strong>
            </div>
            <div className="retention-sources">
              <span>证据来源</span>
              {selected.source_types.map((source) => (
                <SourceBadge
                  key={source}
                  type={source === "question" || source === "agent_practice" ? "question" : "knowledge"}
                >
                  {source === "question"
                    ? "真实作答"
                    : source === "agent_practice"
                      ? "Agent 练习"
                      : source === "agent_discussion"
                        ? "Agent 讲解"
                        : "知识点验证"}
                </SourceBadge>
              ))}
            </div>
            <Button onClick={() => navigate("/practice")}>
              {selected.status === "due" ? "去练习巩固" : "查看练习"}
            </Button>
          </footer>
        </section>
      ) : null}

      <section className="learning-topic-list">
        <SectionHeading meta="按当前保持率由低到高" title="全部关键词轨迹" />
        <div>
          {progress?.topics.map((topic) => (
            <button
              className={
                topic.keyword === selected?.keyword ? "is-selected" : ""
              }
              key={topic.keyword}
              onClick={() => setSelectedKeyword(topic.keyword)}
              type="button"
            >
              <span className={`topic-state topic-state--${topic.status}`} />
              <strong>{topic.keyword}</strong>
              <small>{topic.evidence_count} 条证据</small>
              <em>{topic.retention}%</em>
            </button>
          ))}
        </div>
      </section>

      <section className="learning-activity-log">
        <SectionHeading meta="讨论记录掌握过程，评分证据决定练习结果" title="最近学习记录" />
        {progress?.recent_activities.length ? (
          <ol>
            {progress.recent_activities.map((activity) => (
              <li key={activity.id}>
                <span className={`learning-activity-log__mark is-${activity.source_type}`} />
                <div>
                  <strong>{activity.topic_keywords.join("、") || activity.title || "学习活动"}</strong>
                  <small>
                    {activity.source_type === "agent_discussion"
                      ? "完成 Agent 讲解"
                      : activity.is_correct === true
                        ? "练习回答正确"
                        : activity.is_correct === false
                          ? "练习需要复盘"
                          : "学习活动"}
                  </small>
                </div>
                <time>{new Date(activity.occurred_at).toLocaleString("zh-CN")}</time>
                {activity.session_id ? (
                  <button onClick={() => navigate(`/practice/${activity.session_id}/feedback`)} type="button">
                    查看记录
                  </button>
                ) : activity.thread_id ? (
                  <button onClick={() => navigate(`/agent/${activity.thread_id}`)} type="button">
                    返回对话
                  </button>
                ) : null}
              </li>
            ))}
          </ol>
        ) : <p>完成一次 Agent 讲解或练习后，这里会保留可回溯记录。</p>}
      </section>

      <section className="learning-week">
        <SectionHeading
          meta="只统计已经发生的模拟考和专注计时"
          title="本周真实学习节奏"
        />
        <div>
          {progress?.week.map((item) => (
            <span key={item.date}>
              <i
                style={{
                  height: `${Math.max(3, (item.study_seconds / weekMax) * 100)}%`,
                }}
              />
              <strong>
                {new Intl.DateTimeFormat("zh-CN", { weekday: "short" }).format(
                  new Date(`${item.date}T12:00:00`),
                )}
              </strong>
              <small>
                {item.study_seconds
                  ? `${Math.round(item.study_seconds / 60)} 分`
                  : "—"}
              </small>
            </span>
          ))}
        </div>
      </section>
    </div>
  );
}
