import React from 'react'
import { useParams } from 'react-router-dom'
import { Card, Descriptions, Tag, Timeline } from 'antd'

const PersonPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()

  // TODO: 获取人物详情

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>
      <Card title="人物详情">
        <Descriptions title="基本信息" bordered>
          <Descriptions.Item label="ID">{id}</Descriptions.Item>
          <Descriptions.Item label="姓名">TODO</Descriptions.Item>
          <Descriptions.Item label="英文名">TODO</Descriptions.Item>
          <Descriptions.Item label="出生日期">TODO</Descriptions.Item>
          <Descriptions.Item label="国籍">TODO</Descriptions.Item>
          <Descriptions.Item label="职业">
            <Tag>演员</Tag>
            <Tag>歌手</Tag>
          </Descriptions.Item>
        </Descriptions>

        <Card title="作品" style={{ marginTop: 24 }}>
          TODO
        </Card>

        <Card title="关系" style={{ marginTop: 24 }}>
          TODO
        </Card>

        <Card title="时间线" style={{ marginTop: 24 }}>
          <Timeline
            items={[
              {
                children: '2000年 - 出道',
              },
              {
                children: '2005年 - 首张专辑',
              },
            ]}
          />
        </Card>
      </Card>
    </div>
  )
}

export default PersonPage