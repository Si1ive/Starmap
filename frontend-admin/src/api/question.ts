import adminClient from './client'
import type { ApiResponse, PaginatedResponse, Question } from '@/types'

// ========== 参数类型 ==========

export interface QuestionListParams {
  page?: number
  page_size?: number
  subject_id?: string
  chapter_id?: string
  type?: string
  difficulty?: string
}

export interface UpdateQuestionData {
  content?: string
  options?: { key: string; text: string }[]
  answer?: string
  explanation?: string
  difficulty?: string
  tags?: string[]
  status?: string
}

// ========== 题目 ==========

export const getQuestions = (
  params: QuestionListParams
): Promise<ApiResponse<PaginatedResponse<Question>>> => {
  return adminClient.get('/questions', { params })
}

export const getQuestionDetail = (
  id: string
): Promise<ApiResponse<Question>> => {
  return adminClient.get(`/questions/${id}`)
}

export const updateQuestion = (
  id: string,
  data: UpdateQuestionData
): Promise<ApiResponse<null>> => {
  return adminClient.put(`/questions/${id}`, data)
}
