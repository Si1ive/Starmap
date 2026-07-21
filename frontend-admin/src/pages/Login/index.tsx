import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Form, Input, Button, message } from 'antd'
import { ArrowRightOutlined, LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons'
import { useAdminStore } from '@/store'
import { login } from '@/api'
import type { LoginRequest } from '@/types'
import AdminBrand from '@/components/Brand'

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
    <div className="admin-login">
      <header className="admin-login__header">
        <AdminBrand />
      </header>

      <main className="admin-login__main">
        <section className="admin-login__panel" aria-labelledby="admin-login-title">
          <span className="admin-login__panel-icon" aria-hidden="true">
            <SafetyCertificateOutlined />
          </span>
          <h2 id="admin-login-title">管理员登录</h2>
          <p className="admin-login__hint">使用管理员账号继续。</p>

          <Form<LoginRequest>
            name="login"
            onFinish={handleSubmit}
            autoComplete="off"
            layout="vertical"
            size="large"
            className="admin-login__form"
          >
            <Form.Item
              label="用户名"
              name="username"
              rules={[
                { required: true, message: '请输入用户名' },
                { min: 3, message: '用户名至少3个字符' },
              ]}
            >
              <Input prefix={<UserOutlined />} placeholder="请输入用户名" />
            </Form.Item>

            <Form.Item
              label="密码"
              name="password"
              rules={[
                { required: true, message: '请输入密码' },
                { min: 6, message: '密码至少6个字符' },
              ]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" />
            </Form.Item>

            <Form.Item className="admin-login__submit">
              <Button
                type="primary"
                htmlType="submit"
                loading={loading}
                block
                icon={<ArrowRightOutlined />}
                iconPosition="end"
              >
                登录
              </Button>
            </Form.Item>
          </Form>

          <p className="admin-login__demo">
            <span>测试账号</span>
            <strong>admin / admin123</strong>
          </p>
        </section>
      </main>
    </div>
  )
}

export default Login
