// 管理员用户
export interface AdminUser {
  id: string
  username: string
  nickname: string
  avatar?: string
  role: 'super' | 'super_admin' | 'admin' | 'data_admin' | 'operator'
  permissions: string[]
}

// 登录请求
export interface LoginRequest {
  username: string
  password: string
}

// 登录响应
export interface LoginResponse {
  token: string
  user: AdminUser
}

// 艺人数据
export interface Person {
  id: string
  name: string
  name_en?: string
  avatar?: string
  gender?: 'male' | 'female' | 'unknown'
  birth_date?: string
  birth_place?: string
  nationality?: string
  height?: number
  categories: string[]
  summary?: string
  biography?: string
  status: 'complete' | 'partial' | 'pending' | 'processing'
  source: 'wikipedia' | 'manual'
  created_at: string
  updated_at: string
}

// 作品数据
export interface Work {
  id: string
  title: string
  title_en?: string
  type: 'movie' | 'tv' | 'album' | 'single' | 'book'
  year?: number
  release_date?: string
  description?: string
  summary?: string
  cover?: string
  // 电影特有
  director?: string[]
  actors?: string[]
  box_office?: number
  // 电视剧特有
  episodes?: number
  platform?: string
  // 音乐特有
  artist?: string[]
  record_company?: string
  track_list?: string[]
  // 书籍特有
  author?: string[]
  publisher?: string
  isbn?: string
  // 关联艺人
  related_persons?: { id: string; name: string; role: string }[]
  // 通用
  genres?: string[]
  tags?: string[]
  rating?: number
  status: 'complete' | 'partial' | 'pending'
  source: 'wikipedia' | 'manual'
  created_at: string
  updated_at: string
}

// 爬虫任务
export interface CrawlerTask {
  id: string
  name: string
  task_type: 'full' | 'incremental' | 'targeted' | 'health_check' | 'cleanup'
  source?: string
  source_id?: string
  target_count?: number
  completed_count: number
  success_count: number
  failed_count: number
  success_rate: number
  progress: number
  status: 'pending' | 'running' | 'completed' | 'failed' | 'stopped'
  config?: Record<string, unknown>
  started_at?: string
  completed_at?: string
  created_at?: string
  estimated_completion?: string
  error_message?: string
}

// 数据源
export interface CrawlerSource {
  id: string
  name: string
  code: string
  type: string
  base_url: string
  status: string
  health_status?: string
  config?: Record<string, unknown>
  request_interval?: number
  daily_limit?: number
  concurrent_limit?: number
  total_requests?: number
  total_success?: number
  total_failed?: number
  avg_response_time?: number
  last_health_check?: string
  created_at?: string
  updated_at?: string
}

// 定时任务
export interface CrawlerSchedule {
  id: string
  name: string
  description?: string
  task_type: string
  source_ids?: string[]
  target_config?: Record<string, unknown>
  cron_expression: string
  timezone?: string
  is_enabled: boolean
  max_retries?: number
  retry_interval?: number
  concurrent_limit?: number
  timeout?: number
  total_runs?: number
  success_runs?: number
  failed_runs?: number
  last_run_at?: string
  last_run_status?: string
  next_run_at?: string
  created_at?: string
}

// 爬虫日志
export interface CrawlerLog {
  id: string
  task_id?: string
  source_id?: string
  level: string
  stage?: string
  resource_url?: string
  resource_name?: string
  resource_type?: string
  action?: string
  status?: string
  duration_ms?: number
  message?: string
  error_type?: string
  error_detail?: string
  retry_count?: number
  details?: Record<string, unknown>
  created_at?: string
}

// 已下载文件
export interface DownloadedFile {
  id: string
  task_id?: string
  repo_name?: string
  repo_url?: string
  file_path: string
  file_name: string
  file_type?: string
  file_size?: number
  download_url?: string
  local_path?: string
  status: string
  error_detail?: string
  created_at?: string
  updated_at?: string
}

// 对话记录
export interface Conversation {
  id: string
  first_message: string
  message_count: number
  duration: number
  persons: string[]
  satisfaction?: 'good' | 'needs_improvement' | 'bad'
  created_at: string
}

// 看板统计
export interface DashboardStats {
  person_count?: number
  work_count?: number
  relation_count?: number
  today_chat_count: number
  data_completeness?: number
  api_avg_response?: number
  subject_count: number
  chapter_count: number
  knowledge_point_count: number
  question_count: number
}

// ========== 408考研平台 ==========

// 学科
export interface Subject {
  id: string
  name: string
  code: string
  description?: string
  icon?: string
  sort_order: number
  status: 'active' | 'inactive'
}

// 章节
export interface Chapter {
  id: string
  subject_id: string
  name: string
  description?: string
  sort_order: number
  status: 'active' | 'inactive'
}

// 知识点
export interface KnowledgePoint {
  id: string
  chapter_id: string
  subject_id: string
  title: string
  content: string
  difficulty: 'easy' | 'medium' | 'hard'
  exam_frequency: 'high' | 'medium' | 'low' | 'never'
  tags?: string[]
  key_points?: string[]
  related_point_ids?: string[]
  source?: string
  source_page?: string
  status: 'active' | 'pending' | 'deleted'
  created_at?: string
  updated_at?: string
}

// 题目
export interface Question {
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
  knowledge_point_ids?: string[]
  tags?: string[]
  status: 'active' | 'pending' | 'deleted'
  created_at?: string
  updated_at?: string
}

// 通用分页响应
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// 通用API响应
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
  request_id: string
}

// ========== 多模态入库 ==========

// 语料文件
export interface CorpusFile {
  id: string
  file_name: string
  file_path: string
  file_type: string
  file_ext: string
  file_size: number
  source_type: string
  status: string
  batch_label?: string
  document_id?: string
  created_at?: string
  updated_at?: string
}

// 解析记录
export interface ParseRun {
  id: string
  corpus_file_id: string
  parser_name: DocumentParserName
  parser_version?: string
  parse_mode?: ParseMode
  status: string
  page_count?: number
  block_count?: number
  asset_count?: number
  confidence?: number
  error_detail?: string
  started_at?: string
  completed_at?: string
  created_at?: string
}

export type DocumentParserName = 'docling' | 'mineru'

export type ParseMode = 'primary' | 'fallback' | 'retry' | 'manual_fix'

export interface ParseCorpusFileRequest {
  parser_name?: DocumentParserName
  parse_mode?: ParseMode
}

// 文档 section
export interface DocumentSection {
  id: string
  document_id: string
  title: string
  level: number
  section_path: string
  page_start?: number
  page_end?: number
  parent_id?: string
  children?: DocumentSection[]
}

// Section 映射
export interface SectionMapping {
  mapping_id: string
  section_id: string
  section_title: string
  section_path?: string
  document_id?: string
  canonical_chapter_id: string
  canonical_chapter_name: string
  canonical_chapter_code?: string
  mapping_type: string
  confidence: number
  review_status: string
  review_notes?: string
  created_at?: string
}

// 审核项
export interface ReviewItem {
  id: string
  title?: string
  content?: string
  type?: string
  difficulty?: string
  exam_frequency?: string
  subject_id?: string
  chapter_id?: string
  primary_chapter_id?: string
  topic_terms?: string[]
  source?: string
  review_status: string
  review_notes?: string
  created_at?: string
}

// 关系审核
export interface RelationReview {
  relation_id: string
  source_knowledge_id: string
  source_title: string
  target_knowledge_id: string
  target_title: string
  relation_type: string
  directionality?: string
  evidence_text?: string
  review_status: string
  review_notes?: string
  created_at?: string
}

// 检索结果
export interface SearchResult {
  segment_id: string
  entity_type: string
  entity_id: string
  segment_type: string
  content_text: string
  context_text?: string
  score: number
  subject_id?: string
  chapter_ids?: string[]
  source?: {
    document_id?: string
    filename?: string
    page_no?: number
  }
}

// 检索调试结果
export interface SearchDebugResult {
  primary_results: SearchResult[]
  related_results: SearchResult[]
  relations: Array<{
    relation_id: string
    relation_type: string
    direction: string
    related_knowledge_id: string
    related_knowledge_title: string
    evidence_text?: string
  }>
}

// 标准章节
export interface CanonicalChapter {
  id: string
  subject_id: string
  name: string
  code?: string
  parent_id?: string
  level: number
  sort_order: number
  aliases?: string[]
}
