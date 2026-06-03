import apiClient from './client'

export interface SearchParams {
  q: string
  category?: string
  page?: number
  page_size?: number
}

export interface Person {
  id: string
  name: string
  name_en?: string
  avatar?: string
  categories: string[]
  birth_date?: string
  birth_place?: string
  nationality?: string
  summary: string
  popularity_score?: number
}

export const searchPersons = (params: SearchParams) => {
  return apiClient.get('/persons/search', { params })
}

export const getPersonDetail = (personId: string) => {
  return apiClient.get(`/persons/${personId}`)
}

export const getPersonRelations = (personId: string, params?: {
  depth?: number
  relation_type?: string
}) => {
  return apiClient.get(`/persons/${personId}/relations`, { params })
}

export const getSimilarPersons = (personId: string, params?: {
  limit?: number
}) => {
  return apiClient.get(`/persons/${personId}/similar`, { params })
}
