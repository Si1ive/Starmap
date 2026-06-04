// 管理员用户
export interface AdminUser {
  id: string
  username: string
  nickname: string
  avatar?: string
  role: 'super' | 'admin' | 'operator'
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
  type: 'movie' | 'tv' | 'album' | 'single' | 'book'
  year?: number
  description?: string
  created_at: string
}

// 爬虫任务
export interface CrawlerTask {
  id: string
  type: 'full' | 'incremental' | 'targeted'
  source: 'wikipedia' | 'douban' | 'other'
  target_count: number
  completed_count: number
  success_count: number
  fail_count: number
  success_rate: number
  progress: number
  status: 'pending' | 'running' | 'completed' | 'failed' | 'stopped'
  started_at?: string
  completed_at?: string
  estimated_completion?: string
  error_message?: string
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
