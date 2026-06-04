import axios, { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios'

// 扩展 ImportMeta 类型
interface ImportMetaEnv {
  VITE_API_BASE_URL?: string
}

interface ImportMetaWithEnv extends ImportMeta {
  env: ImportMetaEnv
}

const apiClient = axios.create({
  // 开发环境使用相对路径，让 Vite 代理转发到后端
  // 生产环境使用完整 URL
  baseURL: (import.meta as unknown as ImportMetaWithEnv).env?.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 添加请求ID
    config.headers['X-Request-ID'] = generateUUID()
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器 - 后端返回原始数据（非包装格式）
// 成功时直接返回 response.data
// 错误时抛出包含 code 和 message 的错误
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    // 直接返回数据，后端返回的就是原始数据（PersonSearchResult, ChatResponse 等）
    return response.data
  },
  (error: AxiosError<BackendErrorResponse>) => {
    // 统一错误处理
    const backendError = error.response?.data
    
    if (backendError) {
      // 后端返回的标准错误格式
      const customError = new Error(backendError.message || '请求失败')
      ;(customError as any).code = backendError.code || 'UNKNOWN_ERROR'
      ;(customError as any).status = error.response?.status || 500
      ;(customError as any).request_id = backendError.request_id
      return Promise.reject(customError)
    }
    
    // 网络错误或其他未知错误
    if (error.code === 'ECONNABORTED') {
      return Promise.reject(new Error('请求超时，请稍后重试'))
    }
    if (!error.response) {
      return Promise.reject(new Error('网络连接失败，请检查后端服务是否启动'))
    }
    
    return Promise.reject(new Error(`请求失败: ${error.message}`))
  }
)

// 后端错误响应格式
interface BackendErrorResponse {
  code: string
  message: string
  request_id: string
  detail?: any
}

function generateUUID(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0
    const v = c === 'x' ? r : (r & 0x3 | 0x8)
    return v.toString(16)
  })
}

export default apiClient
