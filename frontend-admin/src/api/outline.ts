import adminClient from './client'
import type { ApiResponse } from '@/types'

export interface OutlineSummary {
  id: string
  name: string
  year: number
  version: string
  description?: string
  status: string
  is_default: boolean
  release_date?: string
  effective_date?: string
  created_at?: string
}

export interface OutlineChapter {
  id: string
  name: string
  code?: string
  outline_code?: string
  level: number
  parent_id?: string
  subject_id?: string
  sort_order: number
  description?: string
  exam_guidance?: string
  children: OutlineChapter[]
}

export interface OutlinePreviewItem {
  name: string
  outline_code?: string
  code?: string
  aliases?: string[]
  description?: string
  exam_guidance?: string
  sort_order?: number
  children?: OutlinePreviewItem[]
}

export interface OutlineSubjectSplit {
  subject_id: string
  subject_code: string
  subject_name: string
  exam_objective?: string
  total_chapters: number
  max_depth: number
  chapters: OutlinePreviewItem[]
}

export interface OutlineUploadParseResult {
  run_id: string
  corpus_file_id: string
  file_name: string
  status: string
}

export interface OutlineRunDetail {
  id: string
  document_id: string
  outline_id?: string
  outline_name?: string
  file_name?: string
  status: string
  current_stage?: string
  stage_detail?: string
  progress: number
  total_subjects: number
  processed_subjects: number
  successful_subjects: number
  current_subject_name?: string
  created_chapters: number
  updated_chapters: number
  error_detail?: string
  result_summary?: { subjects: OutlineSubjectSplit[] }
  started_at?: string
  completed_at?: string
  created_at?: string
}

// 大纲任务列表中的条目（与 OutlineRunDetail 子集对齐）
export interface OutlineRunListItem {
  id: string
  document_id?: string
  outline_id?: string
  outline_name?: string
  file_name?: string
  status: string
  current_stage?: string
  stage_detail?: string
  progress: number
  total_subjects: number
  processed_subjects: number
  successful_subjects: number
  current_subject_name?: string
  created_chapters: number
  updated_chapters: number
  error_detail?: string
  started_at?: string
  completed_at?: string
  created_at?: string
}

export interface OutlineSubjectInfo {
  subject_id: string
  subject_name: string
  subject_code: string
  exam_objective?: string
  guidance_status: 'pending' | 'generating' | 'done' | 'failed'
  chapter_count: number
}

export interface OutlineImportResult {
  outline_id: string
  outline_name: string
  year: number
  version: string
  created_chapters: number
  updated_chapters: number
  total_chapters: number
}

export const listOutlines = (): Promise<ApiResponse<OutlineSummary[]>> => {
  return adminClient.get('/outlines')
}

export const getOutlineChapters = (
  outlineId: string,
  subjectId?: string,
): Promise<ApiResponse<OutlineChapter[]>> => {
  return adminClient.get(`/outlines/${outlineId}/chapters`, {
    params: subjectId ? { subject_id: subjectId } : undefined,
  })
}

export const getOutlineSubjects = (outlineId: string): Promise<ApiResponse<OutlineSubjectInfo[]>> => {
  return adminClient.get(`/outlines/${outlineId}/subjects`)
}

export const importOutline = (data: {
  subject_id: string
  name: string
  year: number
  content: string
  filename?: string
  version?: string
  description?: string
  set_default?: boolean
}): Promise<ApiResponse<OutlineImportResult>> => {
  return adminClient.post('/outlines/import', data)
}

export const importOutlineFromLLM = (data: {
  name: string
  year: number
  version?: string
  description?: string
  set_default?: boolean
  subjects: OutlineSubjectSplit[]
}): Promise<ApiResponse<OutlineImportResult & { subjects: any[] }>> => {
  return adminClient.post('/outlines/import-from-llm', data)
}

export const generateOutlineGuidance = (
  outlineId: string,
  subjectId: string,
): Promise<ApiResponse<{ guidance_status: string; updated_chapters: number; total_chapters: number }>> => {
  return adminClient.post(`/outlines/${outlineId}/subjects/${subjectId}/generate-guidance`)
}

export const uploadParseOutline = (
  file: File,
  parserName?: string
): Promise<ApiResponse<OutlineUploadParseResult>> => {
  const formData = new FormData()
  formData.append('file', file)
  if (parserName) formData.append('parser_name', parserName)
  return adminClient.post('/outlines/upload-parse', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 10 * 60 * 1000,
  })
}

export const getOutlineRunDetail = (runId: string): Promise<ApiResponse<OutlineRunDetail>> => {
  return adminClient.get(`/outlines/runs/${runId}`)
}

export const listOutlineRuns = (params?: {
  status?: string
  limit?: number
}): Promise<ApiResponse<{ items: OutlineRunListItem[] }>> => {
  return adminClient.get('/outlines/runs', { params })
}

export const deleteOutlineRun = (runId: string): Promise<ApiResponse<{ run_id: string }>> => {
  return adminClient.delete(`/outlines/runs/${runId}`)
}

export const batchDeleteOutlineRuns = (ids: string[]): Promise<ApiResponse<{ deleted_count: number; requested_count: number }>> => {
  return adminClient.post('/outlines/runs/batch-delete', { ids })
}

export const deleteOutline = (outlineId: string): Promise<ApiResponse<{
  outline_id: string
  outline_name: string
  deleted_chapters: number
  message: string
}>> => {
  return adminClient.delete(`/outlines/${outlineId}`)
}
