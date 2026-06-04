import apiClient from './client'
import type { IPerson, IRelationGraph, ISimilarPerson, ISearchResponse } from '@/types'

export interface SearchParams {
  q: string
  category?: string
  page?: number
  page_size?: number
}

// 搜索人物 - 直接返回 PersonSearchResult（后端不包装）
export const searchPersons = async (params: SearchParams): Promise<ISearchResponse> => {
  const response = await apiClient.get('/persons/search', { params })
  return response as unknown as ISearchResponse
}

// 获取人物详情 - 直接返回 Person（后端不包装）
export const getPersonDetail = async (personId: string): Promise<IPerson> => {
  const response = await apiClient.get(`/persons/${personId}`)
  return response as unknown as IPerson
}

// 获取人物关系图谱 - 直接返回 PersonRelationGraph（后端不包装）
export const getPersonRelations = async (
  personId: string,
  params?: {
    depth?: number
    relation_type?: string
  }
): Promise<IRelationGraph> => {
  const response = await apiClient.get(`/persons/${personId}/relations`, { params })
  return response as unknown as IRelationGraph
}

// 获取相似人物推荐 - 直接返回 SimilarPersonResult（后端不包装）
export const getSimilarPersons = async (
  personId: string,
  params?: {
    limit?: number
  }
): Promise<{ items: ISimilarPerson[] }> => {
  const response = await apiClient.get(`/persons/${personId}/similar`, { params })
  return response as unknown as { items: ISimilarPerson[] }
}
