import { useState, useCallback } from 'react'

interface TableParams {
  page: number
  page_size: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

interface UseTableOptions {
  defaultPageSize?: number
  defaultSort?: { sort_by: string; sort_order: 'asc' | 'desc' }
}

/**
 * 表格管理 Hook
 */
export const useTable = (
  options: UseTableOptions = {}
) => {
  const { defaultPageSize = 20, defaultSort } = options

  const [params, setParams] = useState<TableParams>({
    page: 1,
    page_size: defaultPageSize,
    ...defaultSort,
  })

  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  const handlePaginationChange = useCallback(
    (page: number, pageSize: number) => {
      setParams((prev) => ({
        ...prev,
        page,
        page_size: pageSize,
      }))
    },
    []
  )

  const handleSortChange = useCallback(
    (sortBy: string, sortOrder: 'asc' | 'desc') => {
      setParams((prev) => ({
        ...prev,
        sort_by: sortBy,
        sort_order: sortOrder,
        page: 1,
      }))
    },
    []
  )

  const handleSearch = useCallback(
    (searchParams: Record<string, any>) => {
      setParams((prev) => ({
        ...prev,
        ...searchParams,
        page: 1,
      }))
    },
    []
  )

  const handleReset = useCallback(() => {
    setParams({
      page: 1,
      page_size: defaultPageSize,
      ...defaultSort,
    })
    setSelectedRowKeys([])
  }, [defaultPageSize, defaultSort])

  const handleSelectionChange = useCallback((keys: React.Key[]) => {
    setSelectedRowKeys(keys)
  }, [])

  return {
    params,
    selectedRowKeys,
    setParams,
    handlePaginationChange,
    handleSortChange,
    handleSearch,
    handleReset,
    handleSelectionChange,
  }
}
