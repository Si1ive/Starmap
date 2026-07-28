import { fetchCurrentSession } from "../auth";

const BASE = "/api/v1/app/practice";

interface Envelope<T> {
  data?: T;
  detail?: string;
  message?: string;
}

export interface PracticePaper {
  document_id: string;
  title: string;
  year: number | null;
  scope: string | null;
  question_count: number;
  origin: "platform" | "personal";
}

export interface PracticeQuestion {
  id: string;
  order_no: number;
  type: string;
  content: string;
  options: Array<{ key?: string; label?: string; text?: string }>;
  max_score: number;
  source: string | null;
  question_no: string | null;
  chapter_id: string | null;
  user_answer: string;
  time_spent_seconds: number;
  is_correct: boolean | null;
  awarded_score: number | null;
  standard_answer: string | null;
  explanation: string | null;
}

export interface PracticeSession {
  id: string;
  title: string;
  mode: "mock_exam" | "practice";
  status: "active" | "submitted";
  duration_seconds: number;
  elapsed_seconds: number;
  remaining_seconds: number;
  question_count: number;
  total_score: number;
  awarded_score: number | null;
  started_at: string;
  submitted_at: string | null;
  questions: PracticeQuestion[];
}

export interface PracticeHistoryItem {
  id: string;
  title: string;
  status: "active" | "submitted";
  question_count: number;
  total_score: number;
  awarded_score: number | null;
  started_at: string;
  submitted_at: string | null;
}

export interface PracticeStats {
  answered_count: number;
  correct_count: number;
  covered_chapters: number;
  total_chapters: number;
  coverage_rate: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body !== undefined) {
    const session = await fetchCurrentSession();
    if (!session) throw new Error("请先登录");
    headers.set("Content-Type", "application/json");
    headers.set("X-CSRF-Token", session.csrf_token);
  }
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
  const envelope = (await response.json().catch(() => ({}))) as Envelope<T>;
  if (!response.ok || envelope.data === undefined) {
    throw new Error(envelope.detail || envelope.message || "练习服务请求失败");
  }
  return envelope.data;
}

export async function listPracticePapers() {
  return (await request<{ items: PracticePaper[] }>("/papers")).items;
}

export async function listPracticeHistory() {
  return (await request<{ items: PracticeHistoryItem[] }>("/history")).items;
}

export function getPracticeStats() {
  return request<PracticeStats>("/stats");
}

export function createPracticeSession(
  documentId: string,
  mode: "mock_exam" | "practice",
  questionCount: number,
  durationSeconds: number,
) {
  return request<PracticeSession>("/sessions", {
    method: "POST",
    body: JSON.stringify({
      document_id: documentId,
      mode,
      question_count: questionCount,
      duration_seconds: durationSeconds,
    }),
  });
}

export function getPracticeSession(sessionId: string) {
  return request<PracticeSession>(`/sessions/${encodeURIComponent(sessionId)}`);
}

export function savePracticeAnswer(
  sessionId: string,
  questionId: string,
  answer: string,
  timeSpentSeconds: number,
) {
  return request<{ saved_at: string }>(
    `/sessions/${encodeURIComponent(sessionId)}/answers/${encodeURIComponent(questionId)}`,
    {
      method: "PUT",
      body: JSON.stringify({ answer, time_spent_seconds: timeSpentSeconds }),
    },
  );
}

export function submitPracticeSession(sessionId: string) {
  return request<PracticeSession>(
    `/sessions/${encodeURIComponent(sessionId)}/submit`,
    { method: "POST", body: "{}" },
  );
}

export function startStudyTimer(
  phase: "focus" | "rest",
  plannedSeconds: number,
) {
  return request<{ id: string; started_at: string }>("/timers", {
    method: "POST",
    body: JSON.stringify({ phase, planned_seconds: plannedSeconds }),
  });
}

export function completeStudyTimer(timerId: string, actualSeconds: number) {
  return request<{ id: string; status: string }>(
    `/timers/${encodeURIComponent(timerId)}/complete`,
    { method: "POST", body: JSON.stringify({ actual_seconds: actualSeconds }) },
  );
}
