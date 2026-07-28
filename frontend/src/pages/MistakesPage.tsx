import { useCallback, useEffect, useState } from "react";
import {
  ArrowRight,
  BookOpenCheck,
  CalendarCheck2,
  History,
  ListChecks,
  RotateCcw,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  getLearningWeaknesses,
  type LearningWeaknesses,
  type WeaknessCluster,
} from "../api/learning";
import { Button, PageHeading, SectionHeading, StatusMark } from "../components/Primitives";

const statusCopy: Record<WeaknessCluster["status"], string> = {
  due: "到期复习",
  scheduled: "等待间隔",
  awaiting_interval_verification: "待再次验证",
};

function shortDate(value: string | undefined) {
  return value
    ? new Date(value).toLocaleString("zh-CN", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "时间未知";
}

export default function MistakesPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<LearningWeaknesses | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getLearningWeaknesses());
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "知识薄弱点加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const lead = data?.clusters[0];
  return (
    <div className="page page--wide mistakes-page">
      <PageHeading
        actions={
          <Button icon={<BookOpenCheck size={17} />} onClick={() => navigate("/practice")}>
            去练习
          </Button>
        }
        description="这里只汇总当前账号已交卷题目的错误事实，并按相同关键词形成待验证队列；不会把一次错误直接写成性格或能力判断。"
        eyebrow="知识诊断"
        title="用真实错误证据安排下一次验证"
      />

      {error ? (
        <div className="practice-alert">
          {error} <button onClick={() => void load()} type="button">重新加载</button>
        </div>
      ) : null}

      {!loading && !lead ? (
        <section className="source-empty">
          <ListChecks size={20} />
          <strong>当前账号还没有已交卷错题</strong>
          <span>完成一次真实模拟考或练习后，错误会按题目关键词进入这里。</span>
          <Button onClick={() => navigate("/practice")}>开始练习</Button>
        </section>
      ) : null}

      {lead ? (
        <section className="review-queue">
          <SectionHeading
            meta={`${data?.summary.due_count ?? 0} 个到期 · ${data?.summary.wrong_answer_count ?? 0} 次错误事实`}
            title="待巩固队列"
          />
          <div className="review-queue__lead">
            <span className="review-queue__index">01</span>
            <span className="review-queue__icon"><RotateCcw size={19} /></span>
            <span>
              <strong>{lead.keyword}</strong>
              <small>真实错误 {lead.wrong_count} 次 · 共作答 {lead.attempt_count} 次</small>
              <em>最近错误：{shortDate(lead.last_wrong_at)} · {statusCopy[lead.status]}</em>
            </span>
            <span><History size={15} /> {statusCopy[lead.status]}</span>
            <Button
              icon={<ArrowRight size={16} />}
              onClick={() => navigate(`/practice/${lead.representative.session_id}/feedback`)}
            >
              复盘原题
            </Button>
          </div>
        </section>
      ) : null}

      {data?.clusters.length ? (
        <section className="mistake-clusters">
          <SectionHeading
            meta={`${data.summary.cluster_count} 个关键词簇 · 仅来自当前账号`}
            title="知识薄弱点"
          />
          <div className="mistake-cluster-list">
            {data.clusters.map((cluster, index) => (
              <button
                className={index === 0 ? "is-active" : ""}
                key={cluster.keyword}
                onClick={() => navigate(`/practice/${cluster.representative.session_id}/feedback`)}
                type="button"
              >
                <span className="mistake-cluster-list__count">{cluster.wrong_count}</span>
                <span className="mistake-cluster-list__copy">
                  <span>
                    <strong>{cluster.keyword}</strong>
                    <StatusMark tone={cluster.status === "due" ? "warning" : "neutral"}>
                      {statusCopy[cluster.status]}
                    </StatusMark>
                  </span>
                  <p>{cluster.representative.content}</p>
                  <small>{cluster.representative.source || cluster.representative.session_title}</small>
                </span>
                <span className="mistake-cluster-list__next">
                  <History size={16} />
                  <small>下一次复习</small>
                  <strong>{shortDate(cluster.next_review_at)}</strong>
                </span>
                <ArrowRight size={17} />
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {data?.timeline.length ? (
        <section className="mistake-history">
          <SectionHeading meta="按真实交卷时间倒序" title="近期错误轨迹" />
          <div className="history-line">
            {data.timeline.slice(0, 8).map((item, index) => (
              <div key={`${item.session_id}-${item.question_id}-${item.occurred_at}`}>
                <span>{index === 0 ? <CalendarCheck2 size={16} /> : <ListChecks size={16} />}</span>
                <strong>{shortDate(item.occurred_at)}</strong>
                <p>{item.session_title} · {item.question_no ? `第 ${item.question_no} 题 · ` : ""}{item.content}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
