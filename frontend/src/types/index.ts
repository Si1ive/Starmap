// ========== 408考研平台类型定义 ==========

// 学科
export interface ISubject {
  id: string
  name: string
  code: string
  description?: string
  icon?: string
  sort_order: number
}

// 章节
export interface IChapter {
  id: string
  subject_id: string
  name: string
  description?: string
  sort_order: number
}

// 知识点
export interface IKnowledgePoint {
  id: string
  chapter_id: string
  subject_id: string
  title: string
  content: string
  difficulty: 'easy' | 'medium' | 'hard'
  exam_frequency: 'high' | 'medium' | 'low' | 'never'
  tags?: string[]
  key_points?: string[]
  source?: string
  source_page?: string
}

// 知识点列表项
export interface IKnowledgePointListItem {
  id: string
  chapter_id: string
  subject_id: string
  title: string
  content: string  // 截断后的内容
  difficulty: 'easy' | 'medium' | 'hard'
  exam_frequency: 'high' | 'medium' | 'low' | 'never'
  tags?: string[]
  source?: string
}

// 题目
export interface IQuestion {
  id: string
  subject_id: string
  chapter_id: string
  type: 'choice' | 'fill' | 'judge' | 'short_answer' | 'design' | 'analysis'
  content: string
  options?: { key: string; text: string }[]
  answer: string
  explanation?: string
  difficulty: 'easy' | 'medium' | 'hard'
  source?: string
  exam_year?: number
  tags?: string[]
}

// 消息类型
export interface IMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: string | null
  sources?: Array<{
    type: string
    title?: string | null
    content?: string | null
  }>
}

// 对话响应
export interface IChatResponse {
  session_id: string
  message: string
  type: 'answer' | 'clarification' | 'error'
  sources: Array<{
    type: string
    title?: string | null
    content?: string | null
  }>
  suggestions: string[]
}

// 对话历史
export interface IChatHistory {
  session_id: string
  messages: IMessage[]
  created_at?: string | null
  updated_at?: string | null
}

// 搜索响应
export interface ISearchResponse {
  items: IKnowledgePointListItem[]
  total: number
  page: number
  page_size: number
}

// API通用响应
export interface IApiResponse<T> {
  code: number
  message: string
  data: T
  request_id: string
}
