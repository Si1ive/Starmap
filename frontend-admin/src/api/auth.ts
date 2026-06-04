import adminClient from './client'
import type { LoginRequest, LoginResponse, ApiResponse, AdminUser } from '@/types'

export const login = (data: LoginRequest): Promise<ApiResponse<LoginResponse>> => {
  return adminClient.post('/auth/login', data)
}

export const logout = (): Promise<ApiResponse<null>> => {
  return adminClient.post('/auth/logout')
}

export const getCurrentUser = (): Promise<ApiResponse<AdminUser>> => {
  return adminClient.get('/auth/me')
}
