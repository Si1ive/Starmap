import { useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  ApiOutlined,
  CheckCircleOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  StarOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import PageHeader from '@/components/PageHeader'
import {
  createAgentModel,
  listAgentModels,
  setDefaultAgentModel,
  testAgentModel,
  updateAgentModel,
  updateAgentModelAvailability,
  type AgentModelConfig,
  type AgentModelConfigInput,
} from '@/api/agentModels'

const SECRET_KEEP_MASK = '__KEEP_EXISTING__'

type ModelFormValues = AgentModelConfigInput

const defaultFormValues: ModelFormValues = {
  display_name: '',
  provider: 'openai_compatible',
  base_url: '',
  api_key: '',
  model_name: '',
  online: false,
  selectable: true,
  is_default: false,
  temperature: 0.2,
  max_tokens: 2000,
  timeout_seconds: 60,
}

const AgentModelsPage = () => {
  const queryClient = useQueryClient()
  const [form] = Form.useForm<ModelFormValues>()
  const maxTokens = Form.useWatch('max_tokens', form)
  const [editing, setEditing] = useState<AgentModelConfig | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [statusId, setStatusId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const modelsQuery = useQuery({
    queryKey: ['adminAgentModels'],
    queryFn: listAgentModels,
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['adminAgentModels'] })

  const saveMutation = useMutation({
    mutationFn: async (values: ModelFormValues) => {
      const input: AgentModelConfigInput = { ...values, provider: 'openai_compatible' }
      if (editing) {
        if (!input.api_key?.trim()) delete input.api_key
        return updateAgentModel(editing.id, input)
      }
      return createAgentModel(input)
    },
    onSuccess: (response) => {
      message.success(response.message || (editing ? '模型配置已更新' : '模型配置已创建'))
      setModalOpen(false)
      setEditing(null)
      form.resetFields()
      refresh()
    },
  })

  const defaultMutation = useMutation({
    mutationFn: setDefaultAgentModel,
    onSuccess: (response) => {
      message.success(response.message || '默认模型已切换')
      refresh()
    },
  })

  const openCreate = () => {
    setEditing(null)
    setTestResult(null)
    form.setFieldsValue(defaultFormValues)
    setModalOpen(true)
  }

  const openEdit = (model: AgentModelConfig) => {
    setEditing(model)
    setTestResult(null)
    form.setFieldsValue({
      display_name: model.display_name,
      provider: model.provider,
      base_url: model.base_url,
      api_key: '',
      model_name: model.model_name,
      online: model.online,
      selectable: model.selectable,
      is_default: model.is_default,
      temperature: model.temperature,
      max_tokens: model.max_tokens,
      timeout_seconds: model.timeout_seconds,
    })
    setModalOpen(true)
  }

  const changeAvailability = async (
    model: AgentModelConfig,
    patch: Partial<Pick<AgentModelConfig, 'online' | 'selectable'>>,
  ) => {
    setStatusId(model.id)
    try {
      const response = await updateAgentModelAvailability(model.id, {
        online: patch.online ?? model.online,
        selectable: patch.selectable ?? model.selectable,
      })
      message.success(response.message || '模型状态已更新')
      await refresh()
    } catch {
      // 错误提示由统一响应拦截器展示；这里吞掉 rejected Promise，避免事件处理器产生未处理异常。
    } finally {
      setStatusId(null)
    }
  }

  const runTest = async (model: AgentModelConfig) => {
    setTestingId(model.id)
    setTestResult(null)
    try {
      const response = await testAgentModel(model.id)
      const result = response.data
      if (result.success) {
        const text = result.reply ? `模型回复：${result.reply}` : '连接成功'
        setTestResult({ type: 'success', text })
        message.success(`${model.display_name} 连通性测试成功`)
      } else {
        setTestResult({ type: 'error', text: result.error || response.message || '模型连接失败' })
      }
    } catch {
      setTestResult({ type: 'error', text: '请求失败，请根据接口提示检查配置' })
    } finally {
      setTestingId(null)
    }
  }

  const columns: ColumnsType<AgentModelConfig> = [
    {
      title: '显示名称',
      dataIndex: 'display_name',
      key: 'display_name',
      width: 190,
      render: (name: string, model) => (
        <Space size={6}>
          <Typography.Text strong>{name}</Typography.Text>
          {model.is_default ? <Tag color="green" icon={<StarOutlined />}>默认</Tag> : null}
        </Space>
      ),
    },
    {
      title: '模型标识',
      dataIndex: 'model_name',
      key: 'model_name',
      ellipsis: true,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    {
      title: '密钥',
      dataIndex: 'has_api_key',
      key: 'has_api_key',
      width: 90,
      render: (hasKey: boolean) => hasKey
        ? <Tag color="green" icon={<CheckCircleOutlined />}>已配置</Tag>
        : <Tag>未配置</Tag>,
    },
    {
      title: '上线',
      dataIndex: 'online',
      key: 'online',
      width: 86,
      render: (online: boolean, model) => (
        <Tooltip title={model.is_default && online ? '默认模型需先切换后才能下线' : undefined}>
          <Switch
            size="small"
            checked={online}
            loading={statusId === model.id}
            onChange={(checked) => changeAvailability(model, { online: checked })}
          />
        </Tooltip>
      ),
    },
    {
      title: '用户可选',
      dataIndex: 'selectable',
      key: 'selectable',
      width: 104,
      render: (selectable: boolean, model) => (
        <Switch
          size="small"
          checked={selectable}
          loading={statusId === model.id}
          onChange={(checked) => changeAvailability(model, { selectable: checked })}
        />
      ),
    },
    {
      title: '输出 Token',
      dataIndex: 'max_tokens',
      key: 'max_tokens',
      width: 110,
      render: (value: number | null) => value === null ? <Tag color="blue">无限</Tag> : value,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (value: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 250,
      fixed: 'right',
      render: (_, model) => (
        <Space size={4} wrap>
          <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEdit(model)}>
            编辑
          </Button>
          <Button
            type="text"
            size="small"
            icon={<ApiOutlined />}
            loading={testingId === model.id}
            onClick={() => runTest(model)}
          >
            测试
          </Button>
          {model.is_default ? null : (
            <Popconfirm
              title="设为默认模型？"
              description="后续未显式选择模型的 Agent Run 将使用它。"
              onConfirm={() => defaultMutation.mutate(model.id)}
              disabled={!model.online || !model.selectable}
            >
              <Tooltip title={!model.online || !model.selectable ? '模型需先上线并设为用户可选' : undefined}>
                <Button
                  type="text"
                  size="small"
                  icon={<StarOutlined />}
                  disabled={!model.online || !model.selectable}
                  loading={defaultMutation.isPending && defaultMutation.variables === model.id}
                >
                  设为默认
                </Button>
              </Tooltip>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div className="agent-models-page">
      <PageHeader
        eyebrow="Agent Runtime"
        title="Agent 模型配置"
        description="集中维护 OpenAI 兼容模型。用户只能看到已上线且允许选择的显示名称，密钥不会在页面回显。"
        actions={(
          <Space>
            <Button icon={<ReloadOutlined />} loading={modelsQuery.isFetching} onClick={() => modelsQuery.refetch()}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增模型</Button>
          </Space>
        )}
      />

      {testResult ? (
        <Alert
          className="agent-models-page__result"
          type={testResult.type}
          showIcon
          closable
          message={testResult.type === 'success' ? '连通性测试成功' : '连通性测试失败'}
          description={testResult.text}
          onClose={() => setTestResult(null)}
        />
      ) : null}

      <Card className="agent-models-page__table" bordered={false}>
        <Table<AgentModelConfig>
          rowKey="id"
          columns={columns}
          dataSource={modelsQuery.data?.data?.items ?? []}
          loading={modelsQuery.isLoading}
          pagination={false}
          scroll={{ x: 1120 }}
          locale={{ emptyText: '尚未配置 Agent 模型，请先新增一个模型' }}
        />
      </Card>

      <Modal
        className="admin-modal"
        title={editing ? `编辑模型：${editing.display_name}` : '新增 Agent 模型'}
        open={modalOpen}
        width={720}
        confirmLoading={saveMutation.isPending}
        okText="保存"
        cancelText="取消"
        onOk={() => form.submit()}
        onCancel={() => {
          setModalOpen(false)
          setEditing(null)
          form.resetFields()
        }}
      >
        <Form<ModelFormValues>
          form={form}
          layout="vertical"
          initialValues={defaultFormValues}
          onFinish={(values) => saveMutation.mutate(values)}
        >
          <div className="agent-model-form__grid">
            <Form.Item label="显示名称" name="display_name" rules={[{ required: true, whitespace: true, message: '请输入显示名称' }]}>
              <Input placeholder="例如：通用模型" maxLength={100} />
            </Form.Item>
            <Form.Item label="模型标识" name="model_name" rules={[{ required: true, whitespace: true, message: '请输入模型标识' }]}>
              <Input placeholder="例如：gpt-4.1-mini" maxLength={200} />
            </Form.Item>
          </div>
          <Form.Item label="Base URL" name="base_url" extra="留空时使用客户端默认地址；填写时无需以 / 结尾。">
            <Input placeholder="https://api.example.com/v1" maxLength={500} />
          </Form.Item>
          <Form.Item
            label="API Key"
            name="api_key"
            extra={editing?.has_api_key ? `已保存密钥；留空将保留原值（服务端掩码：${SECRET_KEEP_MASK}）` : '密钥仅用于后端调用，不会再次明文回显。'}
          >
            <Input.Password placeholder={editing?.has_api_key ? '留空以保留现有密钥' : '请输入 API Key'} maxLength={2000} autoComplete="new-password" />
          </Form.Item>
          <div className="agent-model-form__grid agent-model-form__grid--three">
            <Form.Item label="Temperature" name="temperature" rules={[{ required: true }]}>
              <InputNumber min={0} max={2} step={0.1} precision={2} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              label="最大输出 Token"
              extra="无限时不会向模型供应商发送输出 Token 上限，实际输出仍受模型上下文与供应商限制。"
            >
              <Space.Compact style={{ width: '100%' }}>
                <Form.Item name="max_tokens" noStyle>
                  <InputNumber
                    min={1}
                    max={200000}
                    precision={0}
                    disabled={maxTokens === null}
                    style={{ width: 'calc(100% - 72px)' }}
                  />
                </Form.Item>
                <Switch
                  checked={maxTokens === null}
                  checkedChildren="无限"
                  unCheckedChildren="限额"
                  onChange={(checked) => form.setFieldValue('max_tokens', checked ? null : 2000)}
                />
              </Space.Compact>
            </Form.Item>
            <Form.Item label="超时秒数" name="timeout_seconds" rules={[{ required: true }]}>
              <InputNumber min={5} max={600} precision={0} style={{ width: '100%' }} />
            </Form.Item>
          </div>
          <div className="agent-model-form__switches">
            <Form.Item label="上线" name="online" valuePropName="checked"><Switch /></Form.Item>
            <Form.Item label="用户可选" name="selectable" valuePropName="checked"><Switch /></Form.Item>
            <Form.Item
              label="设为默认"
              name="is_default"
              valuePropName="checked"
              extra={editing?.is_default ? '请先在列表中将另一模型设为默认。' : undefined}
            >
              <Switch disabled={Boolean(editing?.is_default)} />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </div>
  )
}

export default AgentModelsPage
