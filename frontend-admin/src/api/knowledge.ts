import adminClient from './client'
import type { ApiResponse, PaginatedResponse, KnowledgePoint, Subject, Chapter } from '@/types'

// ========== 参数类型 ==========

export interface KnowledgePointListParams {
  page?: number
  page_size?: number
  subject_id?: string
  chapter_id?: string
  difficulty?: string
  keyword?: string
}

export interface UpdateKnowledgePointData {
  title?: string
  content?: string
  difficulty?: string
  exam_frequency?: string
  tags?: string[]
  key_points?: string[]
  status?: string
}

// ========== 学科 ==========

export const getSubjects = (): Promise<ApiResponse<Subject[]>> => {
  return adminClient.get('/subjects')
}

// ========== 章节 ==========

export const getChapters = (subjectId: string): Promise<ApiResponse<Chapter[]>> => {
  return adminClient.get(`/subjects/${subjectId}/chapters`)
}

// ========== 知识点 ==========

export const getKnowledgePoints = (
  params: KnowledgePointListParams
): Promise<ApiResponse<PaginatedResponse<KnowledgePoint>>> => {
  return adminClient.get('/knowledge/points', { params })
}

export const getKnowledgePointDetail = (
  id: string
): Promise<ApiResponse<KnowledgePoint>> => {
  return adminClient.get(`/knowledge/points/${id}`)
}

export const updateKnowledgePoint = (
  id: string,
  data: UpdateKnowledgePointData
): Promise<ApiResponse<null>> => {
  return adminClient.put(`/knowledge/points/${id}`, data)
}
