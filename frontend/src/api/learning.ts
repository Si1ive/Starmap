export interface RetentionPoint {
  day: number;
  retention: number;
}

export interface LearningTopic {
  keyword: string;
  retention: number;
  strength_hours: number;
  last_studied_at: string;
  next_review_at: string;
  evidence_count: number;
  correct_count: number;
  curve: RetentionPoint[];
  status: "due" | "stable";
  source_types: string[];
}

export interface LearningActivity {
  id: number;
  event_type: "practice_answer_graded" | "agent_explanation_completed" | string;
  source_type: "question" | "agent_practice" | "agent_discussion" | string;
  source_id: string;
  topic_keywords: string[];
  knowledge_point_ids: string[];
  evidence_type: string;
  evidence_outcome: "unknown" | "correct" | "partial" | "incorrect" | "ungradable" | string;
  assessment_source: string | null;
  evidence_strength: number;
  assessment_confidence: number | null;
  model_version: string | null;
  knowledge_point_coverage: Record<string, number>;
  is_correct: boolean | null;
  occurred_at: string;
  session_id: string | null;
  thread_id: string | null;
  run_id: string | null;
  title: string | null;
}

export interface LearningProgress {
  generated_at: string;
  summary: {
    learned_keywords: number;
    due_keywords: number;
    answered_questions: number;
    correct_questions: number;
    accuracy_rate: number;
  };
  topics: LearningTopic[];
  recent_activities: LearningActivity[];
}

export interface WeaknessEvidence {
  source_type: string;
  source_id: string;
  session_id: string | null;
  session_title: string;
  question_id: string | null;
  question_no: string | null;
  content: string;
  source: string | null;
  is_correct: boolean;
  occurred_at?: string;
  hint_levels_used: string[];
  thread_id: string | null;
  run_id: string | null;
}

export interface WeaknessCluster {
  keyword: string;
  wrong_count: number;
  attempt_count: number;
  last_wrong_at: string;
  next_review_at: string;
  status: "due" | "scheduled" | "awaiting_interval_verification";
  representative: WeaknessEvidence;
  recent_evidence: WeaknessEvidence[];
}

export interface LearningWeaknesses {
  generated_at: string;
  summary: {
    cluster_count: number;
    wrong_answer_count: number;
    due_count: number;
  };
  clusters: WeaknessCluster[];
  timeline: WeaknessEvidence[];
}

export async function getLearningProgress(): Promise<LearningProgress> {
  const response = await fetch("/api/v1/app/learning/progress", {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  const payload = (await response.json().catch(() => ({}))) as {
    data?: LearningProgress;
    detail?: string;
    message?: string;
  };
  if (!response.ok || !payload.data) {
    throw new Error(payload.detail || payload.message || "学习进度加载失败");
  }
  return payload.data;
}

export async function getLearningWeaknesses(): Promise<LearningWeaknesses> {
  const response = await fetch("/api/v1/app/learning/weaknesses", {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  const payload = (await response.json().catch(() => ({}))) as {
    data?: LearningWeaknesses;
    detail?: string;
    message?: string;
  };
  if (!response.ok || !payload.data) {
    throw new Error(payload.detail || payload.message || "知识薄弱点加载失败");
  }
  return payload.data;
}
