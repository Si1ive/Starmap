import adminClient from './client'
import type {
  ApiResponse,
  PaginatedResponse,
  CorpusFile,
  ParseRun,
  ParseCorpusFileRequest,
  DocumentSection,
  SectionMapping,
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

export const parseCorpusFile = (id: string, req?: ParseCorpusFileRequest): Promise<ApiResponse<any>> => {
  return adminClient.post(`/corpus/files/${id}/parse`, req, {
    timeout: 15 * 60 * 1000,
  })
}

export const registerCorpusFile = (file_path: string, batch_label?: string): Promise<ApiResponse<{ corpus_file_id: string; status: string; is_new: boolean }>> => {
  return adminClient.post('/corpus/files/register', { file_path, batch_label })
}

export const registerCorpusFileByDownload = (downloaded_file_id: string, batch_label?: string): Promise<ApiResponse<{ corpus_file_id: string; status: string; is_new: boolean }>> => {
  return adminClient.post('/corpus/files/register-by-download', { downloaded_file_id, batch_label })
}

// ========== 文档 ==========

export const getDocumentDetail = (id: string): Promise<ApiResponse<any>> => {
  return adminClient.get(`/corpus/documents/${id}`)
}

export const getDocumentSections = (id: string, tree = false): Promise<ApiResponse<DocumentSection[]>> => {
  return adminClient.get(`/corpus/documents/${id}/sections`, { params: { tree } })
}

export const extractDocumentSections = (id: string): Promise<ApiResponse<any>> => {
  return adminClient.post(`/corpus/documents/${id}/extract-sections`)
}

export const mapDocumentChapters = (id: string, subjectId?: string): Promise<ApiResponse<any>> => {
  return adminClient.post(`/corpus/documents/${id}/map-chapters`, null, {
    params: subjectId ? { subject_id: subjectId } : undefined,
  })
}

export const getSectionMappings = (id: string, reviewStatus?: string): Promise<ApiResponse<SectionMapping[]>> => {
  return adminClient.get(`/corpus/documents/${id}/section-mappings`, { params: { review_status: reviewStatus } })
}

export const extractDocumentEntities = (id: string): Promise<ApiResponse<any>> => {
  return adminClient.post(`/corpus/documents/${id}/extract-entities`)
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

export const buildSegments = (params: {
  subject_id?: string
  document_id?: string
  rebuild?: boolean
}): Promise<ApiResponse<any>> => {
  return adminClient.post('/segments/build', null, { params })
}
