import React from 'react'
import { useParams } from 'react-router-dom'
import { Card } from 'antd'

const GraphPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()

  // TODO: 实现关系图谱可视化

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <Card title="关系图谱">
        <div style={{ height: 600, background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <p>人物ID: {id}</p>
          <p>TODO: 实现D3.js力导向图</p>
        </div>
      </Card>
    </div>
  )
}

export default GraphPage