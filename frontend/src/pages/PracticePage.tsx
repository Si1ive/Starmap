import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bookmark,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Loader2,
  Save,
  X,
  XCircle,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getPracticeSession,
  PracticeApiError,
  savePracticeAnswer,
  submitPracticeSession,
} from "../api/practice";
import type { PracticeSession } from "../api/practice";
import { Button, IconButton, SourceBadge } from "../components/Primitives";

function clock(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return `${hours ? `${String(hours).padStart(2, "0")}:` : ""}${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

interface AnswerConflict {
  questionId: string;
  localAnswer: string;
  serverAnswer: string;
  serverVersion: number;
  timeSpentSeconds: number;
}

export default function PracticePage() {
  const navigate = useNavigate();
  const { sessionId, view } = useParams();
  const [session, setSession] = useState<PracticeSession | null>(null);
  const [position, setPosition] = useState(0);
  const [answer, setAnswer] = useState("");
  const [remaining, setRemaining] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [conflict, setConflict] = useState<AnswerConflict | null>(null);
  const questionStartedAt = useRef(Date.now());

  const load = useCallback(async () => {
    if (!sessionId) return;
    try {
      const data = await getPracticeSession(sessionId);
      setSession(data);
      setRemaining(data.remaining_seconds);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "试卷加载失败");
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!session || session.status !== "active" || remaining <= 0) return;
    const interval = window.setInterval(
      () => setRemaining((value) => Math.max(0, value - 1)),
      1000,
    );
    return () => window.clearInterval(interval);
  }, [remaining, session]);
  useEffect(() => {
    if (session?.status === "active" && remaining === 0) void submit();
    // submit intentionally runs only when the server-derived countdown reaches zero.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remaining, session?.status]);

  const question = session?.questions[position];
  useEffect(() => {
    if (conflict?.questionId === question?.id) return;
    setAnswer(question?.user_answer ?? "");
    questionStartedAt.current = Date.now();
  }, [conflict?.questionId, question?.id, question?.user_answer]);

  const answeredCount = useMemo(
    () =>
      session?.questions.filter((item) => item.user_answer.trim()).length ?? 0,
    [session],
  );

  const save = async () => {
    if (!session || !question || session.status !== "active" || conflict) return false;
    setSaving(true);
    try {
      const saved = await savePracticeAnswer(
        session.id,
        question.id,
        answer,
        question.time_spent_seconds +
          Math.floor((Date.now() - questionStartedAt.current) / 1000),
        question.version,
      );
      setSession((current) =>
        current
          ? {
              ...current,
              questions: current.questions.map((item) =>
                item.id === question.id
                  ? { ...item, user_answer: answer, version: saved.version }
                  : item,
              ),
            }
          : current,
      );
      questionStartedAt.current = Date.now();
      setError(null);
      return true;
    } catch (saveError) {
      if (saveError instanceof PracticeApiError && saveError.status === 409) {
        try {
          const latest = await getPracticeSession(session.id);
          const serverQuestion = latest.questions.find((item) => item.id === question.id);
          if (serverQuestion) {
            setSession(latest);
            setConflict({
              questionId: question.id,
              localAnswer: answer,
              serverAnswer: serverQuestion.user_answer,
              serverVersion: serverQuestion.version,
              timeSpentSeconds:
                question.time_spent_seconds +
                Math.floor((Date.now() - questionStartedAt.current) / 1000),
            });
            setAnswer(answer);
            setError(null);
          }
        } catch (reloadError) {
          setError(
            reloadError instanceof Error ? reloadError.message : "冲突版本读取失败",
          );
        }
      } else {
        setError(saveError instanceof Error ? saveError.message : "答案保存失败");
      }
      return false;
    } finally {
      setSaving(false);
    }
  };

  const resolveConflict = async (keepLocal: boolean) => {
    if (!session || !conflict) return;
    if (!keepLocal) {
      setAnswer(conflict.serverAnswer);
      setConflict(null);
      setError("已保留服务器上的较新答案");
      return;
    }
    setSaving(true);
    try {
      const saved = await savePracticeAnswer(
        session.id,
        conflict.questionId,
        conflict.localAnswer,
        conflict.timeSpentSeconds,
        conflict.serverVersion,
      );
      setSession((current) =>
        current
          ? {
              ...current,
              questions: current.questions.map((item) =>
                item.id === conflict.questionId
                  ? {
                      ...item,
                      user_answer: conflict.localAnswer,
                      version: saved.version,
                    }
                  : item,
              ),
            }
          : current,
      );
      setAnswer(conflict.localAnswer);
      setConflict(null);
      setError("已按你的选择用本机答案覆盖服务器版本");
      questionStartedAt.current = Date.now();
    } catch (conflictError) {
      setError(
        conflictError instanceof Error ? conflictError.message : "冲突处理失败，请重新加载",
      );
    } finally {
      setSaving(false);
    }
  };

  const move = async (next: number) => {
    if (!(await save())) return;
    setPosition(
      Math.max(0, Math.min((session?.question_count ?? 1) - 1, next)),
    );
  };

  async function submit() {
    if (!session || submitting || session.status !== "active") return;
    setSubmitting(true);
    try {
      if (!(await save())) return;
      const result = await submitPracticeSession(session.id);
      setSession(result);
      navigate(`/practice/${session.id}/feedback`, { replace: true });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "交卷失败");
    } finally {
      setSubmitting(false);
    }
  }

  if (error && !session)
    return (
      <div className="page">
        <div className="practice-alert">{error}</div>
        <Button onClick={() => navigate("/practice")}>返回练习</Button>
      </div>
    );
  if (!session || !question)
    return (
      <div className="app-loading">
        <span />
        <strong>正在打开真实试卷</strong>
      </div>
    );

  const feedback = view === "feedback" || session.status === "submitted";
  return (
    <div className="practice-shell practice-session-real">
      <header className="practice-topbar">
        <IconButton label="退出练习" onClick={() => navigate("/practice")}>
          <X size={20} />
        </IconButton>
        <div className="practice-progress">
          <span>{session.title}</span>
          <strong>
            第 {position + 1} / {session.question_count} 题 · 已答{" "}
            {answeredCount}
          </strong>
        </div>
        <div className="practice-topbar__actions">
          <span
            className={`practice-timer ${remaining < 300 && !feedback ? "is-urgent" : ""}`}
          >
            <Clock3 size={16} />
            {feedback ? "已交卷" : clock(remaining)}
          </span>
          <span className="autosave">
            <Save size={15} />
            {saving ? "保存中" : "服务器保存"}
          </span>
        </div>
      </header>

      {feedback ? (
        <main className="practice-feedback-real">
          <section className="practice-score-sheet">
            <span>成绩</span>
            <strong>{session.awarded_score ?? 0}</strong>
            <em>/ {session.total_score}</em>
            <p>
              系统按当前题库标准答案自动批改；每道题的原答案与解析保留在下方。
            </p>
          </section>
          <section className="practice-review-list">
            {session.questions.map((item, index) => (
              <button
                className={index === position ? "is-active" : ""}
                key={item.id}
                onClick={() => setPosition(index)}
                type="button"
              >
                {item.is_correct ? (
                  <CheckCircle2 size={16} />
                ) : (
                  <XCircle size={16} />
                )}
                <span>{index + 1}</span>
              </button>
            ))}
          </section>
          <section className="practice-question-card">
            <div className="question-kicker">
              <SourceBadge type="question">复盘</SourceBadge>
              <span>{question.source || "已入库真题"}</span>
              <span>
                {question.awarded_score ?? 0} / {question.max_score} 分
              </span>
            </div>
            <h1>{question.content}</h1>
            {question.options.map((option, index) => (
              <p className="review-option" key={option.key || index}>
                {option.key || option.label || String.fromCharCode(65 + index)}.{" "}
                {option.text}
              </p>
            ))}
            <div className="answer-review">
              <div>
                <span>你的答案</span>
                <strong>{question.user_answer || "未作答"}</strong>
              </div>
              <div>
                <span>标准答案</span>
                <strong>{question.standard_answer}</strong>
              </div>
            </div>
            {question.explanation ? (
              <div className="answer-explanation">
                <span>解析</span>
                <p>{question.explanation}</p>
              </div>
            ) : null}
          </section>
        </main>
      ) : (
        <main className="practice-exam-real">
          <aside>
            <span>答题卡</span>
            <div>
              {session.questions.map((item, index) => (
                <button
                  className={`${index === position ? "is-current" : ""} ${item.user_answer.trim() ? "is-answered" : ""}`}
                  key={item.id}
                  onClick={() => void move(index)}
                  type="button"
                >
                  {index + 1}
                </button>
              ))}
            </div>
            <p>答题时间和答案都保存到当前账号。</p>
          </aside>
          <section className="practice-question-card">
            <div className="question-kicker">
              <SourceBadge type="question">原题</SourceBadge>
              <span>{question.source || "已入库真题"}</span>
              <span>{question.max_score} 分</span>
            </div>
            <h1>{question.content}</h1>
            {question.options.length ? (
              <div className="real-option-list">
                {question.options.map((option, index) => {
                  const key =
                    option.key ||
                    option.label ||
                    String.fromCharCode(65 + index);
                  return (
                    <button
                      className={answer === key ? "is-selected" : ""}
                      key={key}
                      onClick={() => {
                        setAnswer(key);
                      }}
                      type="button"
                    >
                      <span>{key}</span>
                      <strong>{option.text}</strong>
                    </button>
                  );
                })}
              </div>
            ) : (
              <textarea
                aria-label="作答内容"
                onBlur={() => void save()}
                onChange={(event) => setAnswer(event.target.value)}
                placeholder="在这里输入答案"
                value={answer}
              />
            )}
          </section>
        </main>
      )}

      {conflict ? (
        <section aria-live="assertive" className="practice-answer-conflict" role="alertdialog">
          <div>
            <strong>检测到其他设备保存了这道题</strong>
            <p>请选择保留哪个版本，系统不会静默覆盖较新的作答。</p>
          </div>
          <dl>
            <div>
              <dt>服务器答案</dt>
              <dd>{conflict.serverAnswer || "未作答"}</dd>
            </div>
            <div>
              <dt>本机答案</dt>
              <dd>{conflict.localAnswer || "未作答"}</dd>
            </div>
          </dl>
          <div>
            <Button onClick={() => void resolveConflict(false)} tone="quiet">
              使用服务器答案
            </Button>
            <Button disabled={saving} onClick={() => void resolveConflict(true)}>
              用本机答案覆盖
            </Button>
          </div>
        </section>
      ) : null}

      <footer className="practice-footer">
        <Button
          disabled={position === 0}
          icon={<ChevronLeft size={17} />}
          onClick={() => void move(position - 1)}
          tone="quiet"
        >
          上一题
        </Button>
        <div>
          {error ? (
            <span className="text-error">{error}</span>
          ) : (
            <span>
              {feedback ? "逐题核对答案与解析" : "交卷后不可修改答案"}
            </span>
          )}
          {feedback ? (
            <Button onClick={() => navigate("/practice")}>返回练习记录</Button>
          ) : position < session.question_count - 1 ? (
            <Button
              icon={<ChevronRight size={17} />}
              onClick={() => void move(position + 1)}
            >
              保存并下一题
            </Button>
          ) : (
            <Button
              disabled={submitting}
              icon={
                submitting ? (
                  <Loader2 className="spin" size={17} />
                ) : (
                  <Bookmark size={17} />
                )
              }
              onClick={() => void submit()}
            >
              交卷并批改
            </Button>
          )}
        </div>
      </footer>
    </div>
  );
}
