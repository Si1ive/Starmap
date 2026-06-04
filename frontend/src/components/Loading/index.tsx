import React from 'react'
import { Spin, Empty } from 'antd'

interface LoadingProps {
  loading: boolean
  empty?: boolean
  emptyDescription?: string
  children: React.ReactNode
}

const Loading: React.FC<LoadingProps> = ({
  loading,
  empty = false,
  emptyDescription = '暂无数据',
  children
}) => {
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 0' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  if (empty) {
    return <Empty description={emptyDescription} style={{ padding: '40px 0' }} />
  }

  return <>{children}</>
}

export default Loading
