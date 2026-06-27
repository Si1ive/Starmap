import adminClient from './client'
import type {
  ApiResponse,
  PaginatedResponse,
  CorpusFile,
  ParseRun,
  ParseCorpusFileRequest,
  CorpusDocument,
  DocumentSection,
  SectionMapping,
  ChapterDiagnostics,
  ReviewItem,
  RelationReview,
  SearchResult,
  SearchDebugResult,
  CanonicalChapter,
} from '@/types'

// ========== 语料管理 ==========

export const scanCorpusFiles = (req: {
  root_path: string
  file_types?: string[]
  batch_label?: string
}): Promise<ApiResponse<{
  registered_count: number
  skipped_count: number
  failed_count: number
  items?: Array<{ id: string; file_name: string; status: string }>
}>> => {
  return adminClient.post('/corpus/files/scan', req)
}

export const listCorpusFiles = (params: {
  page?: number
  page_size?: number
  status?: string
  source_type?: string
  file_ext?: string
  keyword?: string
}): Promise<ApiResponse<PaginatedResponse<CorpusFile>>> => {
  return adminClient.get('/corpus/files', { params })
}

export const getCorpusFileDetail = (id: string): Promise<ApiResponse<CorpusFile & { parse_runs: ParseRun[] }>> => {
  return adminClient.get(`/corpus/files/${id}`)
}

export const parseCorpusFile = (id: string, req?: ParseCorpusFileRequest): Promise<ApiResponse<{
  run_id: string
  status: string
  corpus_file_id: string
}>> => {
  return adminClient.post(`/corpus/files/${id}/parse`, req, {
    timeout: 15 * 60 * 1000,
  })
}

export const getParseRunDetail = (runId: string): Promise<ApiResponse<ParseRun>> => {
  return adminClient.get(`/corpus/parse-runs/${runId}`)
}

export const registerCorpusFile = (file_path: string, batch_label?: string): Promise<ApiResponse<{ corpus_file_id: string; status: string; is_new: boolean }>> => {
  return adminClient.post('/corpus/files/register', { file_path, batch_label })
}

export const registerCorpusFileByDownload = (downloaded_file_id: string, batch_label?: string): Promise<ApiResponse<{ corpus_file_id: string; status: string; is_new: boolean }>> => {
  return adminClient.post('/corpus/files/register-by-download', { downloaded_file_id, batch_label })
}

export const deleteCorpusFile = (id: string): Promise<ApiResponse<{ file_id: string; file_name: string }>> => {
  return adminClient.delete(`/corpus/files/${id}`)
}

export const batchDeleteCorpusFiles = (
  ids: string[]
): Promise<ApiResponse<{ deleted_count: number; requested_count: number }>> => {
  return adminClient.post('/corpus/files/batch-delete', { ids })
}

// ========== 文档 ==========

export const getDocumentDetail = (id: string): Promise<ApiResponse<CorpusDocument>> => {
  return adminClient.get(`/corpus/documents/${id}`)
}

export const getDocumentSections = (id: string, tree = false): Promise<ApiResponse<DocumentSection[]>> => {
  return adminClient.get(`/corpus/documents/${id}/sections`, { params: { tree } })
}

export const extractDocumentSections = (id: string, force = false): Promise<ApiResponse<any>> => {
  return adminClient.post(`/corpus/documents/${id}/extract-sections`, null, {
    params: force ? { force: true } : undefined,
  })
}

export const mapDocumentChapters = (id: string, subjectId?: string, force = false): Promise<ApiResponse<any>> => {
  return adminClient.post(`/corpus/documents/${id}/map-chapters`, null, {
    params: {
      ...(subjectId ? { subject_id: subjectId } : {}),
      ...(force ? { force: true } : {}),
    },
  })
}

export const getSectionMappings = (id: string, reviewStatus?: string): Promise<ApiResponse<SectionMapping[]>> => {
  return adminClient.get(`/corpus/documents/${id}/section-mappings`, { params: { review_status: reviewStatus } })
}

export const getDocumentChapterDiagnostics = (
  id: string,
  params?: { page_no?: number; include_blocks?: boolean }
): Promise<ApiResponse<ChapterDiagnostics>> => {
  return adminClient.get(`/corpus/documents/${id}/chapter-diagnostics`, { params })
}

export const extractDocumentEntities = (id: string, subjectId?: string): Promise<ApiResponse<any>> => {
  return adminClient.post(`/corpus/documents/${id}/extract-entities`, null, {
    params: subjectId ? { subject_id: subjectId } : undefined,
  })
}

export interface ContentOverviewKPBrief {
  id: string
  title: string
  summary?: string | null
  content_preview: string
  topic_terms: string[]
  review_status: string
  status: string
  source_section_path?: string | null
}

export interface ContentOverviewChapter {
  chapter_id: string
  chapter_name: string
  outline_code?: string | null
  keywords: string[]
  description?: string | null
  exam_guidance?: string | null
  knowledge_points: ContentOverviewKPBrief[]
}

export interface ContentOverviewQuestion {
  id: string
  question_no?: string | null
  type: string
  content_preview: string
  options: Array<{ key?: string; text?: string }>
  exam_year: number
  review_status: string
  status: string
  primary_chapter_id?: string | null
  primary_chapter_name?: string | null
  source_section_path?: string | null
}

export interface ContentOverview {
  document_id: string
  title: string
  doc_type: string
  knowledge_chapters: ContentOverviewChapter[]
  ungrouped_knowledge_points: ContentOverviewKPBrief[]
  questions: ContentOverviewQuestion[]
  summary: {
    knowledge_count: number
    question_count: number
    chapter_count: number
    ungrouped_count: number
  }
}

export const getDocumentContentOverview = (id: string): Promise<ApiResponse<ContentOverview>> => {
  return adminClient.get(`/corpus/documents/${id}/content-overview`)
}

// ========== 标准章节 ==========

export const getCanonicalChapters = (subjectId: string, tree = false): Promise<ApiResponse<CanonicalChapter[]>> => {
  return adminClient.get('/canonical-chapters', { params: { subject_id: subjectId, tree } })
}

// ========== 审核 ==========

export const listSectionReviews = (params: {
  subject_id?: string
  review_status?: string
  page?: number
  page_size?: number
}): Promise<ApiResponse<PaginatedResponse<SectionMapping>>> => {
  return adminClient.get('/review/sections', { params })
}

export const reviewSectionMapping = (
  mappingId: string,
  data: { review_status: string; canonical_chapter_id?: string; review_notes?: string }
): Promise<ApiResponse<any>> => {
  return adminClient.post(`/review/sections/${mappingId}`, null, { params: data })
}

export const deleteSectionMapping = (
  id: string
): Promise<ApiResponse<{ id: string }>> => {
  return adminClient.delete(`/review/sections/${id}`)
}

export const batchDeleteSectionMappings = (
  ids: string[]
): Promise<ApiResponse<{ deleted_count: number; requested_count: number }>> => {
  return adminClient.post('/review/sections/batch-delete', { ids })
}

export const listKnowledgeReviews = (params: {
  subject_id?: string
  chapter_id?: string
  review_status?: string
  page?: number
  page_size?: number
}): Promise<ApiResponse<PaginatedResponse<ReviewItem>>> => {
  return adminClient.get('/review/knowledge', { params })
}

export const reviewKnowledgePoint = (
  id: string,
  data: { review_status: string; review_notes?: string; primary_chapter_id?: string; topic_terms?: string[] }
): Promise<ApiResponse<any>> => {
  return adminClient.post(`/review/knowledge/${id}`, null, { params: data })
}

export const listQuestionReviews = (params: {
  subject_id?: string
  chapter_id?: string
  question_type?: string
  review_status?: string
  page?: number
  page_size?: number
}): Promise<ApiResponse<PaginatedResponse<ReviewItem>>> => {
  return adminClient.get('/review/questions', { params })
}

export const reviewQuestion = (
  id: string,
  data: { review_status: string; review_notes?: string; primary_chapter_id?: string }
): Promise<ApiResponse<any>> => {
  return adminClient.post(`/review/questions/${id}`, null, { params: data })
}

export const listRelationReviews = (params: {
  relation_type?: string
  review_status?: string
  subject_id?: string
  page?: number
  page_size?: number
}): Promise<ApiResponse<PaginatedResponse<RelationReview>>> => {
  return adminClient.get('/review/relations', { params })
}

export const reviewRelation = (
  id: string,
  data: { review_status: string; relation_type?: string; directionality?: string; review_notes?: string }
): Promise<ApiResponse<any>> => {
  return adminClient.post(`/review/relations/${id}`, null, { params: data })
}

export const deleteReviewRelation = (
  id: string
): Promise<ApiResponse<{ id: string }>> => {
  return adminClient.delete(`/review/relations/${id}`)
}

export const batchDeleteReviewRelations = (
  ids: string[]
): Promise<ApiResponse<{ deleted_count: number; requested_count: number }>> => {
  return adminClient.post('/review/relations/batch-delete', { ids })
}

export const getReviewStats = (subjectId?: string): Promise<ApiResponse<any>> => {
  return adminClient.get('/review/stats', { params: { subject_id: subjectId } })
}

// ========== 检索 ==========

export const searchDebug = (req: {
  query: string
  subject_id?: string
  chapter_ids?: string[]
  entity_type?: string
  mode?: string
  limit?: number
}): Promise<ApiResponse<{ results: SearchResult[]; total: number; mode: string }>> => {
  return adminClient.post('/search', req)
}

export const searchWithRelations = (req: {
  query: string
  subject_id?: string
  chapter_ids?: string[]
  limit?: number
}): Promise<ApiResponse<SearchDebugResult>> => {
  return adminClient.post('/search/with-relations', req)
}

export const searchDualPath = (req: {
  expanded_query: string
  chapter_ids: string[]
  subject_id?: string
  limit?: number
  per_chapter_cap?: number
}): Promise<ApiResponse<{
  results: any[]
  total: number
  tier1_count: number
  tier2_count: number
}>> => {
  return adminClient.post('/search/dual-path', req)
}

export const buildSegments = (params: {
  subject_id?: string
  document_id?: string
  rebuild?: boolean
}): Promise<ApiResponse<any>> => {
  return adminClient.post('/segments/build', null, { params })
}

export const uploadCorpusFiles = (formData: FormData, batchLabel?: string): Promise<ApiResponse<{
  batch_label: string
  total: number
  success_count: number
  skipped_count: number
  failed_count: number
  success_items: Array<{ file_name: string; corpus_file_id: string; status: string; is_new: boolean }>
  skipped_items: Array<{ file_name: string; corpus_file_id: string; status: string; is_new: boolean }>
  failed_items: Array<{ file_name: string; status: string; error: string }>
}>> => {
  return adminClient.post('/corpus/files/upload', formData, {
    params: batchLabel ? { batch_label: batchLabel } : undefined,
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    timeout: 5 * 60 * 1000, // 5分钟超时
  })
}

export const getDocumentPageAnalysis = (
  documentId: string,
  pageNo: number
): Promise<ApiResponse<{
  document_id: string
  page_no: number
  page_image: string
  page_info: { width: number; height: number }
  blocks: Array<any>
  assets: Array<any>
  raw_parse_data: any
  parser_name?: string
}>> => {
  return adminClient.get(`/corpus/documents/${documentId}/page-analysis`, {
    params: { page_no: pageNo },
    timeout: 30000, // PDF渲染可能较慢
  })
}
