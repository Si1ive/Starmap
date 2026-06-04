import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Form, Input, Button, Card, message, Typography } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useAdminStore } from '@/store'
import { login } from '@/api'
import type { LoginRequest } from '@/types'

const { Title } = Typography

const Login = () => {
  const navigate = useNavigate()
  const { setUser, setToken, setPermissions } = useAdminStore()
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (values: LoginRequest) => {
    setLoading(true)
    try {
      const response = await login(values)
      if (response.code === 200) {
        const { token, user } = response.data
        setToken(token)
        setUser(user)
        setPermissions(user.permissions)
        message.success('登录成功')
        navigate('/admin/dashboard')
      } else {
        message.error(response.message || '登录失败')
      }
    } catch (error) {
      console.error('登录错误:', error)
      message.error('登录失败，请检查用户名和密码')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      }}
    >
      <Card
        style={{
          width: 420,
          borderRadius: 16,
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.1)',
        }}
        bodyStyle={{ padding: '40px' }}
      >
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <Title level={2} style={{ margin: 0, color: '#667eea' }}>
            StarMap Admin
          </Title>
          <p style={{ color: '#666', marginTop: 8 }}>后台管理系统</p>
        </div>

        <Form<LoginRequest>
          name="login"
          onFinish={handleSubmit}
          autoComplete="off"
          size="large"
        >
          <Form.Item
            name="username"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 3, message: '用户名至少3个字符' },
            ]}
          >
            <Input
              prefix={<UserOutlined style={{ color: '#bfbfbf' }} />}
              placeholder="用户名"
            />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 6, message: '密码至少6个字符' },
            ]}
          >
            <Input.Password
              prefix={<LockOutlined style={{ color: '#bfbfbf' }} />}
              placeholder="密码"
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, marginTop: 24 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              style={{
                height: 48,
                fontSize: 16,
                background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                border: 'none',
              }}
            >
              登录
            </Button>
          </Form.Item>
        </Form>

        <div style={{ marginTop: 24, textAlign: 'center', color: '#999', fontSize: 12 }}>
          <p>演示账号: admin / admin123</p>
        </div>
      </Card>
    </div>
  )
}

export default Login
