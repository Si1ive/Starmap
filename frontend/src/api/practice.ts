import { fetchCurrentSession } from "../auth";

const BASE = "/api/v1/app/practice";

interface Envelope<T> {
  data?: T;
  detail?: string;
  message?: string;
}

export class PracticeApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "PracticeApiError";
    this.status = status;
  }
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
  version: number;
  hint_levels_used: Array<"direction" | "concept" | "method">;
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
  status: "draft" | "active" | "submitted";
  duration_seconds: number;
  elapsed_seconds: number;
  remaining_seconds: number;
  question_count: number;
  total_score: number;
  awarded_score: number | null;
  started_at: string | null;
  submitted_at: string | null;
  questions: PracticeQuestion[];
}

export interface PracticeHistoryItem {
  id: string;
  title: string;
  status: "draft" | "active" | "submitted";
  question_count: number;
  total_score: number;
  awarded_score: number | null;
  started_at: string | null;
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
    throw new PracticeApiError(
      envelope.detail || envelope.message || "练习服务请求失败",
      response.status,
    );
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

export function startPracticeSession(sessionId: string) {
  return request<PracticeSession>(
    `/sessions/${encodeURIComponent(sessionId)}/start`,
    { method: "POST", body: "{}" },
  );
}

export function savePracticeAnswer(
  sessionId: string,
  questionId: string,
  answer: string,
  timeSpentSeconds: number,
  expectedVersion: number,
) {
  return request<{ saved_at: string; version: number }>(
    `/sessions/${encodeURIComponent(sessionId)}/answers/${encodeURIComponent(questionId)}`,
    {
      method: "PUT",
      body: JSON.stringify({
        answer,
        time_spent_seconds: timeSpentSeconds,
        expected_version: expectedVersion,
      }),
    },
  );
}

export function requestPracticeHint(
  sessionId: string,
  questionId: string,
  level: "direction" | "concept" | "method",
  expectedVersion: number,
) {
  return request<{
    level: "direction" | "concept" | "method";
    hint: string;
    version: number;
    hint_levels_used: Array<"direction" | "concept" | "method">;
  }>(
    `/sessions/${encodeURIComponent(sessionId)}/answers/${encodeURIComponent(questionId)}/hints`,
    {
      method: "POST",
      body: JSON.stringify({ level, expected_version: expectedVersion }),
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
