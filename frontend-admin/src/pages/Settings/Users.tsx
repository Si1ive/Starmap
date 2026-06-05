import { useState } from 'react'
import { Card, Table, Tag, Button, Modal, Form, Input, Select, Switch, Row, Col, Statistic, message, Tooltip, Popconfirm } from 'antd'
import {
  UserOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  LockOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import adminClient from '@/api/client'

// API
const getUsers = () => adminClient.get('/users')
const createUser = (data: any) => adminClient.post('/users', data)
const updateUser = (id: string, data: any) => adminClient.put(`/users/${id}`, data)
const deleteUser = (id: string) => adminClient.delete(`/users/${id}`)

interface AdminUser {
  id: string
  username: string
  email: string
  role: 'super_admin' | 'data_admin' | 'operator'
  permissions: string[]
  is_active: boolean
  last_login_at: string | null
  created_at: string
}

const roleConfig: Record<string, { color: string; text: string; desc: string }> = {
  super_admin: { color: 'red', text: '超级管理员', desc: '拥有所有权限' },
  data_admin: { color: 'blue', text: '数据管理员', desc: '数据看板、艺人/作品管理、爬虫管理' },
  operator: { color: 'green', text: '运营人员', desc: '对话管理、基础数据查看' },
}

const permissionOptions = [
  { label: '数据看板', value: 'dashboard:view' },
  { label: '艺人管理', value: 'person:manage' },
  { label: '作品管理', value: 'work:manage' },
  { label: '爬虫管理', value: 'crawler:manage' },
  { label: '对话管理', value: 'conversation:view' },
  { label: '系统监控', value: 'monitor:view' },
  { label: '系统配置', value: 'settings:manage' },
  { label: '用户管理', value: 'user:manage' },
]

const SettingsUsers = () => {
  const queryClient = useQueryClient()
  const [modalVisible, setModalVisible] = useState(false)
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null)
  const [form] = Form.useForm()

  const { data, isLoading } = useQuery({
    queryKey: ['adminUsers'],
    queryFn: getUsers,
  })

  const createMutation = useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      message.success('用户创建成功')
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      setModalVisible(false)
      form.resetFields()
    },
    onError: () => message.error('创建失败'),
  })

  const updateMutation = useMutation({
    mutationFn: (params: { id: string; data: any }) => updateUser(params.id, params.data),
    onSuccess: () => {
      message.success('用户更新成功')
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      setModalVisible(false)
      setEditingUser(null)
      form.resetFields()
    },
    onError: () => message.error('更新失败'),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteUser,
    onSuccess: () => {
      message.success('用户已删除')
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
    },
    onError: () => message.error('删除失败'),
  })

  const userList: AdminUser[] = (data?.data?.users || []) as AdminUser[]

  const handleEdit = (user: AdminUser) => {
    setEditingUser(user)
    form.setFieldsValue({
      username: user.username,
      email: user.email,
      role: user.role,
      permissions: user.permissions,
      is_active: user.is_active,
    })
    setModalVisible(true)
  }

  const handleCreate = () => {
    setEditingUser(null)
    form.resetFields()
    form.setFieldsValue({ is_active: true, role: 'operator' })
    setModalVisible(true)
  }

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      // 角色映射到默认权限
      const roleDefaultPermissions: Record<string, string[]> = {
        super_admin: permissionOptions.map((p) => p.value),
        data_admin: ['dashboard:view', 'person:manage', 'work:manage', 'crawler:manage', 'monitor:view'],
        operator: ['dashboard:view', 'conversation:view'],
      }
      values.permissions = values.permissions || roleDefaultPermissions[values.role] || []

      if (editingUser) {
        updateMutation.mutate({ id: editingUser.id, data: values })
      } else {
        createMutation.mutate(values)
      }
    })
  }

  const columns = [
    {
      title: '用户名',
      dataIndex: 'username',
      width: 120,
      render: (v: string) => (
        <span>
          <UserOutlined style={{ marginRight: 8 }} />
          {v}
        </span>
      ),
    },
    {
      title: '邮箱',
      dataIndex: 'email',
      width: 180,
    },
    {
      title: '角色',
      dataIndex: 'role',
      width: 130,
      render: (role: string) => {
        const config = roleConfig[role] || { color: 'default', text: role, desc: '' }
        return (
          <Tooltip title={config.desc}>
            <Tag color={config.color}>{config.text}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '权限',
      dataIndex: 'permissions',
      render: (perms: string[]) => {
        const display = perms.slice(0, 3)
        const extra = perms.length - 3
        return (
          <span>
            {display.map((p) => {
              const option = permissionOptions.find((o) => o.value === p)
              return <Tag key={p}>{option?.label || p}</Tag>
            })}
            {extra > 0 && <Tag>+{extra}项</Tag>}
          </span>
        )
      },
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      render: (v: boolean) => v ? <Tag color="success">启用</Tag> : <Tag color="default">禁用</Tag>,
    },
    {
      title: '最后登录',
      dataIndex: 'last_login_at',
      width: 170,
      render: (v: string | null) => v || <span style={{ color: '#999' }}>从未登录</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_: any, record: AdminUser) => (
        <span>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          {record.username !== 'admin' && (
            <Popconfirm title="确定删除此用户？" onConfirm={() => deleteMutation.mutate(record.id)}>
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          )}
        </span>
      ),
    },
  ]

  // 统计
  const activeCount = userList.filter((u) => u.is_active).length
  const roleCount = (role: string) => userList.filter((u) => u.role === role).length

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>用户管理</h2>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="总用户数"
              value={userList.length}
              prefix={<TeamOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="活跃用户"
              value={activeCount}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="超级管理员" value={roleCount('super_admin')} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic title="数据管理员" value={roleCount('data_admin')} />
          </Card>
        </Col>
      </Row>

      {/* 用户列表 */}
      <Card
        title="用户列表"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
            新增用户
          </Button>
        }
      >
        <Table
          columns={columns}
          dataSource={userList}
          rowKey="id"
          loading={isLoading}
          size="small"
          pagination={false}
        />
      </Card>

      {/* 创建/编辑弹窗 */}
      <Modal
        title={editingUser ? '编辑用户' : '新增用户'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => {
          setModalVisible(false)
          setEditingUser(null)
          form.resetFields()
        }}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        width={600}
      >
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label="用户名"
                name="username"
                rules={[{ required: true, message: '请输入用户名' }]}
              >
                <Input prefix={<UserOutlined />} placeholder="请输入用户名" disabled={!!editingUser} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="邮箱"
                name="email"
                rules={[
                  { required: true, message: '请输入邮箱' },
                  { type: 'email', message: '邮箱格式不正确' },
                ]}
              >
                <Input prefix={<LockOutlined />} placeholder="请输入邮箱" />
              </Form.Item>
            </Col>
          </Row>

          {!editingUser && (
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  label="密码"
                  name="password"
                  rules={[{ required: true, message: '请输入密码' }, { min: 6, message: '密码至少6位' }]}
                >
                  <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  label="确认密码"
                  name="password_confirm"
                  dependencies={['password']}
                  rules={[
                    { required: true, message: '请确认密码' },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        if (!value || getFieldValue('password') === value) {
                          return Promise.resolve()
                        }
                        return Promise.reject(new Error('密码不一致'))
                      },
                    }),
                  ]}
                >
                  <Input.Password prefix={<LockOutlined />} placeholder="请确认密码" />
                </Form.Item>
              </Col>
            </Row>
          )}

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="角色" name="role" rules={[{ required: true }]}>
                <Select
                  options={Object.entries(roleConfig).map(([k, v]) => ({
                    label: `${v.text} (${v.desc})`,
                    value: k,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="启用状态" name="is_active" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            label="权限"
            name="permissions"
            tooltip="选择角色后会自动分配默认权限，也可自定义"
          >
            <Select
              mode="multiple"
              options={permissionOptions}
              placeholder="选择权限（角色会自动分配默认权限）"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default SettingsUsers