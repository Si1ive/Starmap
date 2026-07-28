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
  source_types: Array<"question" | "knowledge_point">;
}

export interface LearningProgress {
  generated_at: string;
  summary: {
    learned_keywords: number;
    due_keywords: number;
    answered_questions: number;
    correct_questions: number;
    accuracy_rate: number;
    study_seconds: number;
  };
  topics: LearningTopic[];
  week: Array<{ date: string; study_seconds: number }>;
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
