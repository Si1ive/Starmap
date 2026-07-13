import adminClient from './client'
import type {
  ApiResponse,
  ContentBatchDeleteResult,
  ContentMutationResult,
  ContentReviewResult,
  PaginatedResponse,
  Question,
} from '@/types'

// ========== 参数类型 ==========

export interface QuestionListParams {
  page?: number
  page_size?: number
  subject_id?: string
  chapter_id?: string
  type?: string
  difficulty?: string
  exam_scope?: string
  exam_year?: number
  keyword?: string
  review_status?: string
  status?: string
}

export interface UpdateQuestionData {
  subject_id?: string
  chapter_id?: string
  type?: Question['type']
  content?: string
  options?: { key: string; text: string }[]
  answer?: string
  explanation?: string
  difficulty?: Question['difficulty']
  source?: string
  exam_year?: number
  tags?: string[]
  status?: 'active' | 'pending'
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
): Promise<ApiResponse<ContentMutationResult>> => {
  return adminClient.put(`/questions/${id}`, data)
}

export const deleteQuestion = (
  id: string
): Promise<ApiResponse<ContentMutationResult>> => {
  return adminClient.delete(`/questions/${id}`)
}

export const batchDeleteQuestions = (
  ids: string[]
): Promise<ApiResponse<ContentBatchDeleteResult>> => {
  return adminClient.post('/questions/batch-delete', { ids })
}

export const reviewQuestion = (
  id: string,
  data: {
    review_status: 'approved' | 'rejected'
    review_notes?: string
    primary_chapter_id?: string
  },
): Promise<ApiResponse<ContentReviewResult>> => {
  return adminClient.post(`/review/questions/${id}`, null, { params: data })
}
