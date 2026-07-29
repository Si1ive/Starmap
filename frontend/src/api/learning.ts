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
    activity_retention_keywords?: number;
    mastery_knowledge_points?: number;
    mastery_evidence_count?: number;
  };
  topics: LearningTopic[];
  recent_activities: LearningActivity[];
  activity_retention?: {
    generated_at: string;
    topics: LearningTopic[];
    recent_activities: LearningActivity[];
  };
  mastery_evidence?: {
    generated_at: string;
    knowledge_points: MasteryEvidence[];
    evidence_count: number;
  };
}

export interface MasteryEvidence {
  knowledge_point_id: string;
  knowledge_point_title: string;
  knowledge_point_aliases: string[];
  mastery_score: number;
  raw_mastery_score: number;
  effective_mastery_score: number;
  uncertainty: number;
  evidence_mass: number;
  evidence_count: number;
  correct_count: number;
  incorrect_count: number;
  last_evidence_id: string | null;
  evidence_at: string | null;
  decay_policy_version: string;
  state_model_version: string;
  evidence_sources: Array<Record<string, unknown>>;
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

export interface WeaknessFinding {
  finding_id: string;
  projector_version: string;
  knowledge_point_id: string | null;
  keyword: string | null;
  title: string | null;
  status: "confirmed" | "needs_diagnostic" | "awaiting_interval_verification";
  reason_code: string;
  recommended_review_reason: string;
  severity: number;
  confidence: number;
  wrong_count: number;
  positive_count: number;
  attempt_count: number;
  error_tags: string[];
  evidence_ids: string[];
  evidence_sources: Array<Record<string, unknown>>;
  source_types: string[];
  last_wrong_at: string | null;
  last_evidence_at: string | null;
  next_review_at: string | null;
  hypothesis_expires_at: string | null;
}

export interface LearningWeaknesses {
  generated_at: string;
  summary: {
    cluster_count: number;
    wrong_answer_count: number;
    due_count: number;
    finding_count?: number;
    confirmed_finding_count?: number;
    diagnostic_finding_count?: number;
  };
  clusters: WeaknessCluster[];
  timeline: WeaknessEvidence[];
  findings?: WeaknessFinding[];
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
