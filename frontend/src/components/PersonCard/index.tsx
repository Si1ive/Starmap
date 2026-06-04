import React from 'react'
import { Card, Tag, Typography, Avatar } from 'antd'
import { UserOutlined } from '@ant-design/icons'
import type { IPersonListItem } from '@/types'

const { Text } = Typography

interface PersonCardProps {
  person: IPersonListItem
  onClick?: (id: string) => void
}

const PersonCard: React.FC<PersonCardProps> = ({ person, onClick }) => {
  return (
    <Card
      hoverable
      onClick={() => onClick?.(person.id)}
      style={{ height: '100%' }}
    >
      <Card.Meta
        avatar={
          <Avatar
            size={64}
            src={person.avatar_url || undefined}
            icon={<UserOutlined />}
            style={{ backgroundColor: '#1890ff' }}
          />
        }
        title={
          <div style={{ fontSize: 16, fontWeight: 600 }}>
            {person.name}
          </div>
        }
        description={
          <div>
            <div style={{ marginBottom: 8 }}>
              {person.categories?.map((cat) => (
                <Tag key={cat} color="blue" style={{ marginBottom: 4 }}>
                  {cat}
                </Tag>
              )) || <Tag color="default">其他</Tag>}
            </div>
            <Text type="secondary" ellipsis>
              {person.summary || person.description || '暂无简介'}
            </Text>
            {person.popularity_score !== undefined && person.popularity_score !== null && person.popularity_score > 0 && (
              <div style={{ marginTop: 8 }}>
                <Text type="warning" style={{ fontSize: 12 }}>
                  人气: {person.popularity_score.toFixed(1)}
                </Text>
              </div>
            )}
          </div>
        }
      />
    </Card>
  )
}

export default React.memo(PersonCard)
