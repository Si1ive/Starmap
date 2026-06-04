import React from 'react'
import { Card, Tag, Typography, Avatar } from 'antd'
import { UserOutlined } from '@ant-design/icons'
import type { IPerson } from '@/types'

const { Text } = Typography

interface PersonCardProps {
  person: IPerson
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
            src={person.avatar}
            icon={<UserOutlined />}
            style={{ backgroundColor: '#1890ff' }}
          />
        }
        title={
          <div style={{ fontSize: 16, fontWeight: 600 }}>
            {person.name}
            {person.name_en && (
              <Text type="secondary" style={{ fontSize: 13, marginLeft: 8 }}>
                {person.name_en}
              </Text>
            )}
          </div>
        }
        description={
          <div>
            <div style={{ marginBottom: 8 }}>
              {person.categories.map((cat) => (
                <Tag key={cat} color="blue" style={{ marginBottom: 4 }}>
                  {cat}
                </Tag>
              ))}
            </div>
            {person.birth_date && (
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                出生日期: {person.birth_date}
              </Text>
            )}
            {person.nationality && (
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                国籍: {person.nationality}
              </Text>
            )}
            <Text type="secondary" ellipsis={{ rows: 2 }}>
              {person.summary}
            </Text>
          </div>
        }
      />
    </Card>
  )
}

export default React.memo(PersonCard)
