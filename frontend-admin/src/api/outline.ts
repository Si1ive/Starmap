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
  sort_order: number
  children: OutlineChapter[]
}

export interface OutlinePreviewItem {
  name: string
  outline_code?: string
  code?: string
  aliases?: string[]
  description?: string
  sort_order?: number
  children?: OutlinePreviewItem[]
}

export interface OutlinePreview {
  format: 'json' | 'text' | 'document_sections'
  total_chapters: number
  max_depth: number
  chapters: OutlinePreviewItem[]
}

export interface OutlineUploadParseResult extends OutlinePreview {
  corpus_file_id: string
  document_id: string
  file_name: string
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

export const getOutlineChapters = (outlineId: string): Promise<ApiResponse<OutlineChapter[]>> => {
  return adminClient.get(`/outlines/${outlineId}/chapters`)
}

export const previewOutline = (content: string, filename?: string): Promise<ApiResponse<OutlinePreview>> => {
  return adminClient.post('/outlines/preview', { content, filename })
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

export const importOutlineFromDocument = (data: {
  subject_id: string
  document_id: string
  name: string
  year: number
  version?: string
  set_default?: boolean
}): Promise<ApiResponse<OutlineImportResult>> => {
  return adminClient.post('/outlines/import-from-document', data)
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
    timeout: 5 * 60 * 1000,
  })
}
