// 人物类型
export interface IPerson {
  id: string
  name: string
  name_en?: string
  avatar?: string
  gender?: 'male' | 'female'
  birth_date?: string
  birth_place?: string
  nationality?: string
  height?: number
  summary: string
  biography?: string
  popularity_score?: number
  categories: string[]
}

// 作品类型
export interface IWork {
  id: string
  title: string
  title_en?: string
  type: 'album' | 'movie' | 'tv' | 'drama' | 'book'
  release_date?: string
  genre?: string
  rating?: number
  poster?: string
  summary?: string
}

// 关系类型
export interface IRelation {
  person: IPerson
  type: string
  description: string
}

// 消息类型
export interface IMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

// 搜索响应
export interface ISearchResponse {
  items: IPerson[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// API通用响应
export interface IApiResponse<T> {
  code: number
  message: string
  data: T
  request_id: string
}