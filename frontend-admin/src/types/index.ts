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
  person_count: number
  work_count: number
  relation_count: number
  today_chat_count: number
  data_completeness: number
  api_avg_response: number
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
