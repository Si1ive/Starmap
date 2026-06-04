import adminClient from './client'
import type { ApiResponse, Person, PaginatedResponse } from '@/types'

export interface PersonListParams {
  page?: number
  page_size?: number
  q?: string
  category?: string
  nationality?: string
  gender?: string
  status?: string
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

export const getPersonList = (
  params?: PersonListParams
): Promise<ApiResponse<PaginatedResponse<Person>>> => {
  return adminClient.get('/persons', { params })
}

export const getPersonDetail = (id: string): Promise<ApiResponse<Person>> => {
  return adminClient.get(`/persons/${id}`)
}

export const createPerson = (data: Partial<Person>): Promise<ApiResponse<Person>> => {
  return adminClient.post('/persons', data)
}

export const updatePerson = (id: string, data: Partial<Person>): Promise<ApiResponse<Person>> => {
  return adminClient.put(`/persons/${id}`, data)
}

export const deletePerson = (id: string): Promise<ApiResponse<null>> => {
  return adminClient.delete(`/persons/${id}`)
}

export const batchDeletePersons = (ids: string[]): Promise<ApiResponse<null>> => {
  return adminClient.post('/persons/batch', { ids, action: 'delete' })
}
