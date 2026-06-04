import axios from 'axios'
import { message } from 'antd'
import { useAdminStore } from '@/store'

const adminClient = axios.create({
  baseURL: '/api/v1/admin',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器 - 添加Token
adminClient.interceptors.request.use(
  (config) => {
    const token = useAdminStore.getState().token
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // 添加请求ID
    config.headers['X-Request-ID'] = generateUUID()
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器 - 处理错误
adminClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      message.error('登录已过期，请重新登录')
      useAdminStore.getState().logout()
      window.location.href = '/admin/login'
    } else if (error.response?.status === 403) {
      message.error('没有权限执行此操作')
    } else if (error.response?.status === 429) {
      message.error('请求过于频繁，请稍后重试')
    } else {
      const msg = error.response?.data?.message || '请求失败，请稍后重试'
      message.error(msg)
    }
    return Promise.reject(error)
  }
)

function generateUUID(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

export default adminClient
