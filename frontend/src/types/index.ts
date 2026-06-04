// 人物类型 - 适配后端 Person 模型
export interface IPerson {
  id: string
  name: string
  name_en?: string | null
  avatar?: string | null  // 前端兼容字段，映射 avatar_url
  avatar_url?: string | null  // 后端真实字段
  gender?: 'male' | 'female' | null
  birth_date?: string | null
  birth_place?: string | null
  nationality?: string | null
  height?: number | null
  summary?: string | null
  biography?: string | null
  popularity_score?: number | null
  categories: string[]
  aliases?: string[] | null
}

// 人物列表项 - 适配后端 PersonListItem
export interface IPersonListItem {
  id: string
  name: string
  categories: string[]
  avatar_url?: string | null
  summary?: string | null
  popularity_score?: number | null
  // 兼容旧字段
  category?: string | null
  description?: string | null
}

// 作品类型
export interface IWork {
  id: string
  title: string
  title_en?: string | null
  type: 'album' | 'movie' | 'tv' | 'drama' | 'book'
  release_date?: string | null
  genre?: string | null
  rating?: number | null
  poster?: string | null
  summary?: string | null
}

// 关系类型 - 适配后端 RelationNode
export interface IRelation {
  person: IPerson
  type: string
  description: string
}

// 关系图谱节点
export interface IRelationNode {
  id: string
  name: string
  category?: string | null
  avatar_url?: string | null
}

// 关系图谱边
export interface IRelationEdge {
  source: string
  target: string
  type: string
  properties?: Record<string, any> | null
}

// 关系图谱数据
export interface IRelationGraph {
  center: IRelationNode
  nodes: IRelationNode[]
  edges: IRelationEdge[]
}

// 相似人物
export interface ISimilarPerson {
  id: string
  name: string
  category: string
  avatar_url?: string | null
  similarity_score: number
  common_connections: string[]
}

// 消息类型 - 适配后端 ChatMessage
export interface IMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: string | null
}

// 搜索响应 - 适配后端 PersonSearchResult
export interface ISearchResponse {
  items: IPersonListItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// 对话响应 - 适配后端 ChatResponse
export interface IChatResponse {
  session_id: string
  message: string
  type: 'answer' | 'clarification' | 'error'
  sources: Array<{
    type: string
    title?: string | null
    content?: string | null
    url?: string | null
  }>
  suggestions: string[]
}

// 对话历史 - 适配后端 ChatHistory
export interface IChatHistory {
  session_id: string
  messages: IMessage[]
  created_at?: string | null
  updated_at?: string | null
}

// API通用响应 - 后端标准响应格式
export interface IApiResponse<T> {
  code: string  // "SUCCESS" 或错误码
  message: string
  data: T
  request_id: string
}
