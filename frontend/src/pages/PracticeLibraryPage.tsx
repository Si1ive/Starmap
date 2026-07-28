import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpenCheck,
  Clock3,
  FileQuestion,
  History,
  Loader2,
  Pause,
  Play,
  RotateCcw,
  Target,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  completeStudyTimer,
  createPracticeSession,
  getPracticeStats,
  listPracticeHistory,
  listPracticePapers,
  startStudyTimer,
} from "../api/practice";
import type {
  PracticeHistoryItem,
  PracticePaper,
  PracticeStats,
} from "../api/practice";
import {
  Button,
  EmptyState,
  PageHeading,
  SectionHeading,
  SourceBadge,
} from "../components/Primitives";

function formatClock(seconds: number) {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

export default function PracticeLibraryPage() {
  const navigate = useNavigate();
  const [papers, setPapers] = useState<PracticePaper[]>([]);
  const [history, setHistory] = useState<PracticeHistoryItem[]>([]);
  const [stats, setStats] = useState<PracticeStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [startingPaper, setStartingPaper] = useState<string | null>(null);
  const [timerPhase, setTimerPhase] = useState<"focus" | "rest">("focus");
  const [timerId, setTimerId] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(25 * 60);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextPapers, nextHistory, nextStats] = await Promise.all([
        listPracticePapers(),
        listPracticeHistory(),
        getPracticeStats(),
      ]);
      setPapers(nextPapers);
      setHistory(nextHistory);
      setStats(nextStats);
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "练习数据加载失败",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!timerId || remaining <= 0) return;
    const interval = window.setInterval(
      () => setRemaining((value) => Math.max(0, value - 1)),
      1000,
    );
    return () => window.clearInterval(interval);
  }, [remaining, timerId]);
  useEffect(() => {
    if (!timerId || remaining !== 0) return;
    const planned = timerPhase === "focus" ? 25 * 60 : 5 * 60;
    void completeStudyTimer(timerId, planned).finally(() => setTimerId(null));
  }, [remaining, timerId, timerPhase]);

  const activeHistory = useMemo(
    () => history.filter((item) => item.status === "active"),
    [history],
  );

  const startPaper = async (
    paper: PracticePaper,
    mode: "mock_exam" | "practice",
  ) => {
    setStartingPaper(paper.document_id);
    try {
      const count =
        mode === "mock_exam"
          ? Math.min(paper.question_count, 100)
          : Math.min(paper.question_count, 20);
      const session = await createPracticeSession(
        paper.document_id,
        mode,
        count,
        mode === "mock_exam" ? 3 * 60 * 60 : 25 * 60,
      );
      navigate(`/practice/${session.id}`);
    } catch (startError) {
      setError(
        startError instanceof Error ? startError.message : "无法开始练习",
      );
    } finally {
      setStartingPaper(null);
    }
  };

  const toggleTimer = async () => {
    if (timerId) {
      const planned = timerPhase === "focus" ? 25 * 60 : 5 * 60;
      await completeStudyTimer(timerId, planned - remaining);
      setTimerId(null);
      return;
    }
    const planned = timerPhase === "focus" ? 25 * 60 : 5 * 60;
    const timer = await startStudyTimer(timerPhase, planned);
    setRemaining(planned);
    setTimerId(timer.id);
  };

  const switchPhase = (phase: "focus" | "rest") => {
    if (timerId) return;
    setTimerPhase(phase);
    setRemaining(phase === "focus" ? 25 * 60 : 5 * 60);
  };

  return (
    <div className="page page--wide practice-library-page practice-real">
      <PageHeading
        description="从已经完成入库和题目抽取的真题资料开始。模拟考与薄弱点补强分别记录，不混用语义。"
        eyebrow="练习"
        title="真实模拟考与刷题记录"
      />
      {error ? <div className="practice-alert">{error}</div> : null}

      <section className="practice-dashboard">
        <div>
          <Target size={18} />
          <span>累计做题</span>
          <strong>{stats?.answered_count ?? 0}</strong>
          <small>真实交卷题数</small>
        </div>
        <div>
          <BookOpenCheck size={18} />
          <span>答对</span>
          <strong>{stats?.correct_count ?? 0}</strong>
          <small>按标准答案批改</small>
        </div>
        <div>
          <FileQuestion size={18} />
          <span>大纲覆盖</span>
          <strong>{stats?.coverage_rate ?? 0}%</strong>
          <small>
            {stats?.covered_chapters ?? 0} / {stats?.total_chapters ?? 0} 个考点
          </small>
        </div>
      </section>

      <section className="pomodoro-panel">
        <div className="pomodoro-copy">
          <span className="eyebrow">练习节奏</span>
          <h2>{timerPhase === "focus" ? "刷题" : "休息"}</h2>
          <p>计时记录绑定当前账号，结束后进入真实学习统计。</p>
        </div>
        <strong className="pomodoro-clock">{formatClock(remaining)}</strong>
        <div className="pomodoro-actions">
          <button
            className={timerPhase === "focus" ? "is-active" : ""}
            disabled={Boolean(timerId)}
            onClick={() => switchPhase("focus")}
            type="button"
          >
            刷题 25 分钟
          </button>
          <button
            className={timerPhase === "rest" ? "is-active" : ""}
            disabled={Boolean(timerId)}
            onClick={() => switchPhase("rest")}
            type="button"
          >
            休息 5 分钟
          </button>
          <Button
            icon={timerId ? <Pause size={16} /> : <Play size={16} />}
            onClick={() => void toggleTimer()}
          >
            {timerId ? "结束并记录" : "开始计时"}
          </Button>
        </div>
      </section>

      <section className="practice-papers">
        <SectionHeading
          meta={loading ? "正在读取题库" : `${papers.length} 份可用真题`}
          title="从已入库真题开始"
        />
        {papers.map((paper) => (
          <article key={paper.document_id}>
            <span className="practice-paper-year">{paper.year || "真题"}</span>
            <div>
              <SourceBadge
                type={paper.origin === "personal" ? "personal" : "question"}
              >
                {paper.origin === "personal" ? "个人资料" : "平台真题"}
              </SourceBadge>
              <h3>{paper.title}</h3>
              <p>
                {paper.question_count} 道已抽取题目
                {paper.scope ? ` · ${paper.scope}` : ""}
              </p>
            </div>
            <div>
              <Button
                disabled={startingPaper === paper.document_id}
                icon={
                  startingPaper === paper.document_id ? (
                    <Loader2 className="spin" size={16} />
                  ) : (
                    <Clock3 size={16} />
                  )
                }
                onClick={() => void startPaper(paper, "mock_exam")}
              >
                模拟考
              </Button>
              <Button
                onClick={() => void startPaper(paper, "practice")}
                tone="secondary"
              >
                25 分钟练习
              </Button>
            </div>
          </article>
        ))}
        {!loading && !papers.length ? (
          <EmptyState
            action={
              <Button onClick={() => navigate("/sources")} tone="secondary">
                去资料页
              </Button>
            }
            description="只有真实入库并完成题目抽取、且标记为真题或模拟卷的资料会出现在这里。先到资料页添加 PDF，或等待当前入库任务完成。"
            title="还没有可用真题"
          />
        ) : null}
      </section>

      <section className="practice-history">
        <SectionHeading
          meta={`${history.length} 次真实记录`}
          title="交卷与复盘"
        />
        {history.map((item) => (
          <button
            key={item.id}
            onClick={() =>
              navigate(
                `/practice/${item.id}${item.status === "submitted" ? "/feedback" : ""}`,
              )
            }
            type="button"
          >
            <span>
              {item.status === "active" ? (
                <RotateCcw size={17} />
              ) : (
                <History size={17} />
              )}
            </span>
            <div>
              <strong>{item.title}</strong>
              <small>
                {item.started_at ? new Date(item.started_at).toLocaleString("zh-CN") : "尚未开始"} ·{" "}
                {item.question_count} 题
              </small>
            </div>
            <em>
              {item.status === "submitted"
                ? `${item.awarded_score ?? 0} / ${item.total_score}`
                : "继续作答"}
            </em>
          </button>
        ))}
        {!history.length && !loading ? (
          <p className="practice-history-empty">
            完成一次练习后，成绩、答案和解析会保存在这里。
          </p>
        ) : null}
        {activeHistory.length ? (
          <small className="practice-resume-note">
            有 {activeHistory.length} 场尚未交卷，计时仍以服务器开始时间为准。
          </small>
        ) : null}
      </section>
    </div>
  );
}
