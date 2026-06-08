import client from './client'
import type { IApiResponse, ISearchResponse, IKnowledgePoint, ISubject, IChapter, IQuestion } from '@/types'

// 学科列表
export const getSubjects = (): Promise<IApiResponse<ISubject[]>> => {
  return client.get('/admin/subjects')
}

// 章节列表
export const getChapters = (subjectId: string): Promise<IApiResponse<IChapter[]>> => {
  return client.get(`/admin/subjects/${subjectId}/chapters`)
}

// 知识点搜索
export const searchKnowledgePoints = (params: {
  q?: string
  subject_id?: string
  chapter_id?: string
  difficulty?: string
  page?: number
  page_size?: number
}): Promise<IApiResponse<ISearchResponse>> => {
  return client.get('/admin/knowledge/points', { params })
}

// 知识点详情
export const getKnowledgePointDetail = (id: string): Promise<IApiResponse<IKnowledgePoint>> => {
  return client.get(`/admin/knowledge/points/${id}`)
}

// 题目列表
export const getQuestions = (params: {
  subject_id?: string
  chapter_id?: string
  type?: string
  difficulty?: string
  page?: number
  page_size?: number
}): Promise<IApiResponse<{ items: IQuestion[]; total: number }>> => {
  return client.get('/admin/questions', { params })
}

// 题目详情
export const getQuestionDetail = (id: string): Promise<IApiResponse<IQuestion>> => {
  return client.get(`/admin/questions/${id}`)
}
