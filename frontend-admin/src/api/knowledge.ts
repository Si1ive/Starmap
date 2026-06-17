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

export const getSubjects = async (): Promise<ApiResponse<Subject[]>> => {
  const res: any = await adminClient.get('/subjects')
  return { ...res, data: res.data?.items || [] }
}

// ========== 章节 ==========

export const getChapters = async (subjectId: string): Promise<ApiResponse<Chapter[]>> => {
  const res: any = await adminClient.get(`/subjects/${subjectId}/chapters`)
  return { ...res, data: res.data?.items || [] }
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

export const batchDeleteKnowledgePoints = (
  ids: string[]
): Promise<ApiResponse<{ deleted_count: number; requested_count: number }>> => {
  return adminClient.post('/knowledge/points/batch-delete', { ids })
}

// ========== 旧版 PDF 入库接口 ==========

export interface IngestPdfData {
  pdf_path: string
  subject_id: string
  chapter_id: string
  source?: string
}

export const ingestPdf = (
  data: IngestPdfData
): Promise<ApiResponse<{ task_id: string }>> => {
  return adminClient.post('/knowledge/ingest', data)
}

export const getIngestTasks = (
  params: { page?: number; page_size?: number } = {}
): Promise<ApiResponse<{ items: any[]; total: number; page: number; page_size: number }>> => {
  return adminClient.get('/knowledge/ingest/tasks', { params })
}
