import adminClient from './client'
import type { ApiResponse } from '@/types'

export interface ChapterRelationItem {
  id: string
  source_chapter_id: string
  source_chapter_name: string
  target_chapter_id: string
  target_chapter_name: string
  relation_type: string
  confidence?: number
  source_type: string
  evidence_text?: string
  review_status: string
  review_notes?: string
  created_at?: string
}

export interface ChapterRelationListResult {
  items: ChapterRelationItem[]
  total: number
  page: number
  page_size: number
}

export interface OutlineExpansionResult {
  expanded_query: string
  matched_chapters: Array<{
    chapter_id: string
    name: string
    outline_code: string
    score: number
    keywords: string[]
  }>
  subject_ids: string[]
  chapter_ids: string[]
}

export interface SearchWithOutlineResult {
  results: any[]
  total: number
  mode: string
  outline_expansion: OutlineExpansionResult
}

export interface ScopeChapterEntry {
  chapter_id: string
  relation: string
}

export interface SemanticRelationEntry {
  chapter_id: string
  source_type: string
  relation_type: string
  confidence: number
  evidence_text?: string
}

export interface ChapterExpansionEntry {
  scope_expansion: ScopeChapterEntry[]
  semantic_relations: SemanticRelationEntry[]
}

export interface ChapterExpansionResult {
  relations: Record<string, ChapterExpansionEntry>
}

// 考点关系 CRUD
export const buildChapterRelations = (params?: {
  subject_id?: string
  outline_id?: string
}): Promise<ApiResponse<{ created: number; llm_created: number; embedding_created: number; chapters_processed: number }>> => {
  return adminClient.post('/chapter-relations/build', undefined, { params })
}

export const listChapterRelations = (params: {
  source_chapter_id?: string
  target_chapter_id?: string
  relation_type?: string
  review_status?: string
  source_type?: string
  page?: number
  page_size?: number
}): Promise<ApiResponse<ChapterRelationListResult>> => {
  return adminClient.get('/chapter-relations', { params })
}

export const reviewChapterRelation = (
  id: string,
  data: { review_status: string; review_notes?: string }
): Promise<ApiResponse<{ id: string; review_status: string }>> => {
  return adminClient.post(`/chapter-relations/${id}/review`, undefined, {
    params: data,
  })
}

export const deleteChapterRelation = (
  id: string
): Promise<ApiResponse<{ id: string }>> => {
  return adminClient.delete(`/chapter-relations/${id}`)
}

export const batchDeleteChapterRelations = (
  ids: string[]
): Promise<ApiResponse<{ deleted_count: number; requested_count: number }>> => {
  return adminClient.post('/chapter-relations/batch-delete', { ids })
}

// 跨章关联编排
export const expandChapterRelations = (chapterIds: string[], maxResults?: number): Promise<ApiResponse<ChapterExpansionResult>> => {
  return adminClient.post('/search/chapter-expansion', {
    chapter_ids: chapterIds,
    max_results: maxResults ?? 10,
  })
}

// 大纲扩展检索
export const searchWithOutlineExpansion = (data: {
  query: string
  subject_id?: string
  chapter_ids?: string[]
  entity_type?: string
  mode?: string
  limit?: number
  filters?: Record<string, any>
}): Promise<ApiResponse<SearchWithOutlineResult>> => {
  return adminClient.post('/search/with-outline', data)
}
