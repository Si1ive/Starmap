import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Row, Col, Input, Typography, Space, Tag } from 'antd'
import {
  BookOutlined,
  FormOutlined,
  MessageOutlined,
  ReadOutlined,
  CloudServerOutlined,
  DesktopOutlined,
  GlobalOutlined,
} from '@ant-design/icons'

const { Title, Paragraph } = Typography
const { Search } = Input

const subjectIcons: Record<string, React.ReactNode> = {
  data_structure: <ReadOutlined style={{ fontSize: 32, color: '#1890ff' }} />,
  computer_organization: <CloudServerOutlined style={{ fontSize: 32, color: '#52c41a' }} />,
  operating_system: <DesktopOutlined style={{ fontSize: 32, color: '#722ed1' }} />,
  computer_network: <GlobalOutlined style={{ fontSize: 32, color: '#fa8c16' }} />,
}

const HomePage: React.FC = () => {
  const navigate = useNavigate()

  const subjects = [
    { id: 'subj_ds', name: '数据结构', code: 'data_structure', description: '线性表、树、图、排序、查找', score: '~45分' },
    { id: 'subj_co', name: '计算机组成原理', code: 'computer_organization', description: '数据表示、存储器、CPU、总线、I/O', score: '~45分' },
    { id: 'subj_os', name: '操作系统', code: 'operating_system', description: '进程、内存、文件、I/O管理', score: '~35分' },
    { id: 'subj_cn', name: '计算机网络', code: 'computer_network', description: '物理层到应用层协议体系', score: '~25分' },
  ]

  const features = [
    { icon: <BookOutlined />, title: '结构化知识库', desc: '按408大纲组织，带难度/考频标签' },
    { icon: <MessageOutlined />, title: 'RAG智能问答', desc: '基于知识库的精准回答' },
    { icon: <FormOutlined />, title: '刷题练习', desc: '真题+练习题，支持多种题型' },
  ]

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '40px 24px' }}>
      {/* Hero */}
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <Title level={2}>408考研智能学习平台</Title>
        <Paragraph style={{ fontSize: 16, color: '#666' }}>
          基于RAG的结构化学习系统，覆盖数据结构、计组、操作系统、计网四门学科
        </Paragraph>
        <Search
          placeholder="搜索知识点，如：二叉树遍历、死锁、TCP三次握手"
          size="large"
          style={{ maxWidth: 600, marginTop: 24 }}
          onSearch={(value) => navigate(`/knowledge?q=${encodeURIComponent(value)}`)}
        />
      </div>

      {/* 学科卡片 */}
      <Title level={4} style={{ marginBottom: 16 }}>四大学科</Title>
      <Row gutter={[16, 16]} style={{ marginBottom: 48 }}>
        {subjects.map((subject) => (
          <Col xs={24} sm={12} md={6} key={subject.id}>
            <Card
              hoverable
              onClick={() => navigate(`/knowledge?subject_id=${subject.id}`)}
              style={{ textAlign: 'center' }}
            >
              <div style={{ marginBottom: 12 }}>
                {subjectIcons[subject.code]}
              </div>
              <div style={{ fontSize: 16, fontWeight: 'bold', marginBottom: 8 }}>
                {subject.name}
              </div>
              <div style={{ color: '#666', fontSize: 13, marginBottom: 8 }}>
                {subject.description}
              </div>
              <Tag color="blue">{subject.score}</Tag>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 功能介绍 */}
      <Title level={4} style={{ marginBottom: 16 }}>核心功能</Title>
      <Row gutter={[16, 16]}>
        {features.map((feature, idx) => (
          <Col xs={24} md={8} key={idx}>
            <Card>
              <Space direction="vertical" size="middle">
                <div style={{ fontSize: 24, color: '#1890ff' }}>{feature.icon}</div>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 'bold', marginBottom: 4 }}>{feature.title}</div>
                  <div style={{ color: '#666' }}>{feature.desc}</div>
                </div>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}

export default HomePage
