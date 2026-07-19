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
        <span>内部管理入口</span>
      </header>

      <main className="admin-login__main">
        <section className="admin-login__intro">
          <p className="admin-eyebrow">408 CONTENT OPERATIONS</p>
          <h1>让内容、语料和检索链路保持清晰可查。</h1>
          <p>
            面向知识资产维护、题目治理与模型运行观察的内部工作台。
          </p>
          <dl className="admin-login__signals">
            <div>
              <dt>内容链路</dt>
              <dd>知识 · 题目 · 语料</dd>
            </div>
            <div>
              <dt>运行链路</dt>
              <dd>采集 · 检索 · 模型</dd>
            </div>
          </dl>
        </section>

        <section className="admin-login__panel" aria-labelledby="admin-login-title">
          <span className="admin-login__panel-icon" aria-hidden="true">
            <SafetyCertificateOutlined />
          </span>
          <p className="admin-eyebrow">ADMIN ACCESS</p>
          <h2 id="admin-login-title">登录数据工作台</h2>
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

          <p className="admin-login__demo">演示账号：admin / admin123</p>
        </section>
      </main>

      <footer className="admin-login__footer">
        <span>408 数据工作台</span>
        <span>受控访问 · 2026</span>
      </footer>
    </div>
  )
}

export default Login
