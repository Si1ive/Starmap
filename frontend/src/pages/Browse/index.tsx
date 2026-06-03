import React from 'react'
import { Card, Row, Col, Tag } from 'antd'

const categories = [
  { name: '演员', count: 100 },
  { name: '歌手', count: 80 },
  { name: '导演', count: 50 },
  { name: '编剧', count: 30 },
]

const BrowsePage: React.FC = () => {
  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>
      <h2>领域浏览</h2>
      <Row gutter={[16, 16]}>
        {categories.map(cat => (
          <Col xs={24} sm={12} md={8} lg={6} key={cat.name}>
            <Card hoverable>
              <h3>{cat.name}</h3>
              <Tag color="blue">{cat.count} 人</Tag>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}

export default BrowsePage