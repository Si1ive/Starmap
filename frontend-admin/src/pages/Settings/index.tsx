import { useEffect, useState } from 'react'
import { Alert, Form, Input, InputNumber, Select, Switch, Button, Card, message, Tabs, Tag, Space, Table, Modal } from 'antd'
import { SaveOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getSettings,
  updateSettings,
  getPdfParserHistory,
  getLlmStatus,
  testLlm,
} from '@/api'
import type { SystemSettings, LlmKind, LlmConfig, EmbeddingConfig } from '@/api/settings'

const { TextArea } = Input
const { Option } = Select
const { TabPane } = Tabs

// 对话型 LLM 配置 Tab（问答 / 题目结构 / 大纲拆分共用）
const LlmConfigTab = ({
  kind,
  form,
  intro,
}: {
  kind: Exclude<LlmKind, 'embedding'>
  form: any
  intro: string
}) => {
  const queryClient = useQueryClient()
  const { data: statusData, isLoading: statusLoading } = useQuery({
    queryKey: ['llm-status', kind],
    queryFn: () => getLlmStatus(kind),
    refetchOnWindowFocus: false,
  })
  const status = statusData?.data

  const testMutation = useMutation({
    mutationFn: (cfg: Partial<LlmConfig>) => testLlm(kind, cfg),
    onSuccess: (res) => {
      if (res.code === 200 && res.data?.success) {
        message.success(`测试成功：${res.data.reply || '已连通'}；点击右上角保存配置后生效`)
        queryClient.invalidateQueries({ queryKey: ['llm-status', kind] })
      } else {
        message.error(res.data?.error || res.message || '测试失败')
      }
    },
    onError: () => message.error('测试失败'),
  })

  return (
    <Card>
      <div style={{ display: 'flex', gap: 12, justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap' }}>
        <Alert
          type={status?.is_available ? 'success' : 'info'}
          showIcon
          style={{ flex: 1, minWidth: 280 }}
          message={intro}
          description={
            statusLoading
              ? '正在读取后端配置状态...'
              : status?.is_available
                ? `当前可用：${status.model}，API Key 来源：${status.uses_env_api_key ? '环境变量' : '配置中心'}`
                : (status?.issues?.join('；') || '配置后点击右侧"测试当前配置"验证连通性。')
          }
        />
        <Button
          icon={<ThunderboltOutlined />}
          loading={testMutation.isLoading}
          onClick={() => testMutation.mutate(form.getFieldValue(kind) || {})}
        >
          测试当前配置
        </Button>
      </div>

      <Form.Item name={[kind, 'enabled']} label="启用" valuePropName="checked">
        <Switch />
      </Form.Item>
      <Form.Item name={[kind, 'provider']} label="服务类型">
        <Select>
          <Option value="openai_compatible">OpenAI 兼容接口</Option>
        </Select>
      </Form.Item>
      <Form.Item name={[kind, 'base_url']} label="Base URL" tooltip="OpenAI 官方接口可留空；兼容服务填写类似 https://api.example.com/v1">
        <Input placeholder="https://api.openai.com/v1" />
      </Form.Item>
      <Form.Item name={[kind, 'api_key']} label="API Key" tooltip="留空时后端使用 OPENAI_API_KEY 环境变量">
        <Input.Password placeholder="留空使用环境变量；已保存密钥会显示为保留占位符" autoComplete="new-password" />
      </Form.Item>
      <Form.Item name={[kind, 'model']} label="模型">
        <Input placeholder="如 deepseek-chat / gpt-4o-mini / qwen-plus" />
      </Form.Item>
      <Form.Item name={[kind, 'temperature']} label="温度参数">
        <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name={[kind, 'max_tokens']} label="最大Token数">
        <InputNumber min={100} max={32000} step={100} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name={[kind, 'timeout_seconds']} label="请求超时（秒）">
        <InputNumber min={5} max={600} style={{ width: '100%' }} />
      </Form.Item>
      {kind === 'outline_llm' && (
        <Form.Item name={[kind, 'max_concurrency']} label="增强批次最大并发数" tooltip="控制大纲拆分第2轮批量增强时的并发 LLM 请求数，避免触发限流。默认 3，可根据服务商限流策略调整">
          <InputNumber min={1} max={20} style={{ width: '100%' }} />
        </Form.Item>
      )}
      <Form.Item name={[kind, 'system_prompt']} label="系统提示词">
        <TextArea rows={4} placeholder="输入该用途专用的系统提示词" />
      </Form.Item>
    </Card>
  )
}

// 向量化（embedding）配置 Tab
const EmbeddingConfigTab = ({ form }: { form: any }) => {
  const queryClient = useQueryClient()
  const { data: statusData, isLoading: statusLoading } = useQuery({
    queryKey: ['llm-status', 'embedding'],
    queryFn: () => getLlmStatus('embedding'),
    refetchOnWindowFocus: false,
  })
  const status = statusData?.data

  const testMutation = useMutation({
    mutationFn: (cfg: Partial<EmbeddingConfig>) => testLlm('embedding', cfg),
    onSuccess: (res) => {
      if (res.code === 200 && res.data?.success) {
        const d = res.data
        const dimMsg = d.dimension_match
          ? `维度 ${d.dimension} 与配置一致`
          : `实际维度 ${d.dimension} 与配置 ${d.configured_dimension} 不一致，请修正`
        if (d.dimension_match) message.success(`测试成功：${dimMsg}；点击右上角保存配置后生效`)
        else message.warning(`已连通，但${dimMsg}`)
        queryClient.invalidateQueries({ queryKey: ['llm-status', 'embedding'] })
      } else {
        message.error(res.data?.error || res.message || '测试失败')
      }
    },
    onError: () => message.error('测试失败'),
  })

  return (
    <Card>
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="修改向量化模型或维度需重建向量库"
        description="切换 embedding 模型通常会改变向量维度。维度变化后必须重建 Qdrant collection 并重新生成全部历史向量，否则检索会失效或报错。本页只保存配置，不会自动重灌，请在重新构建 segment 时生效。"
      />
      <div style={{ display: 'flex', gap: 12, justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap' }}>
        <Alert
          type={status?.is_available ? 'success' : 'info'}
          showIcon
          style={{ flex: 1, minWidth: 280 }}
          message="该配置用于知识点/题目文本向量化与检索"
          description={
            statusLoading
              ? '正在读取后端配置状态...'
              : status?.is_available
                ? `当前可用：${status.model}（${status.dimension} 维）${status.provider === 'local_bge_m3' ? '，本地模型无需 API Key' : `，API Key 来源：${status.uses_env_api_key ? '环境变量' : '配置中心'}`}`
                : (status?.issues?.join('；') || '配置后点击"测试当前配置"验证连通性与维度。')
          }
        />
        <Button
          icon={<ThunderboltOutlined />}
          loading={testMutation.isLoading}
          onClick={() => testMutation.mutate(form.getFieldValue('embedding') || {})}
        >
          测试当前配置
        </Button>
      </div>

      <Form.Item name={['embedding', 'enabled']} label="启用" valuePropName="checked">
        <Switch />
      </Form.Item>
      <Form.Item name={['embedding', 'provider']} label="服务类型">
        <Select onChange={(value) => {
          if (value === 'local_bge_m3') {
            form.setFieldsValue({
              embedding: {
                ...form.getFieldValue('embedding'),
                model: 'BAAI/bge-m3',
                dimension: 1024,
              }
            })
          }
        }}>
          <Option value="openai_compatible">OpenAI 兼容接口</Option>
          <Option value="local_bge_m3">本地 BGE-M3 (1024维)</Option>
        </Select>
      </Form.Item>
      <Form.Item
        shouldUpdate={(prev, cur) => prev.embedding?.provider !== cur.embedding?.provider}
        noStyle
      >
        {({ getFieldValue }) => {
          const provider = getFieldValue(['embedding', 'provider'])
          const isLocal = provider === 'local_bge_m3'
          if (isLocal) {
            return (
              <Form.Item
                name={['embedding', 'base_url']}
                label="服务地址"
                tooltip="本地 BGE-M3 由独立容器（infinity）提供 OpenAI 兼容接口。留空则后端默认连 http://bge-m3:7997/v1"
              >
                <Input placeholder="留空使用容器默认地址 http://bge-m3:7997/v1" />
              </Form.Item>
            )
          }
          return (
            <>
              <Form.Item name={['embedding', 'base_url']} label="Base URL">
                <Input placeholder="https://api.openai.com/v1" />
              </Form.Item>
              <Form.Item name={['embedding', 'api_key']} label="API Key" tooltip="留空时后端使用 OPENAI_API_KEY 环境变量">
                <Input.Password placeholder="留空使用环境变量；已保存密钥会显示为保留占位符" autoComplete="new-password" />
              </Form.Item>
            </>
          )
        }}
      </Form.Item>
      <Form.Item name={['embedding', 'model']} label="模型">
        <Input placeholder="如 text-embedding-3-small / bge-m3 / text-embedding-v3" />
      </Form.Item>
      <Form.Item name={['embedding', 'dimension']} label="向量维度" tooltip="必须与所选模型实际输出维度一致。ada-002/3-small=1536，bge-m3=1024">
        <InputNumber min={64} max={8192} step={1} style={{ width: '100%' }} />
      </Form.Item>
      <Form.Item name={['embedding', 'timeout_seconds']} label="请求超时（秒）">
        <InputNumber min={5} max={600} style={{ width: '100%' }} />
      </Form.Item>
    </Card>
  )
}

const Settings = () => {
  const [form] = Form.useForm()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState('llm')

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
    // 切到别的窗口再切回来时不要自动重拉，否则会用服务端旧值覆盖未保存的输入
    refetchOnWindowFocus: false,
  })

  const mutation = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      message.success('保存成功')
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      queryClient.invalidateQueries({ queryKey: ['pdf-parser-history'] })
      queryClient.invalidateQueries({ queryKey: ['llm-status'] })
    },
    onError: () => {
      message.error('保存失败')
    },
  })

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['pdf-parser-history'],
    queryFn: () => getPdfParserHistory(1, 20),
  })

  const handleSubmit = (values: Partial<SystemSettings>) => {
    const nextTarget = values.pdf_parser?.deployment_target
    const currentTarget = parserSettings?.deployment_target
    const switchNotes = values.pdf_parser?.service_switch_notes?.trim() || ''
    const isSwitching = !!nextTarget && !!currentTarget && nextTarget !== currentTarget

    if (nextTarget === 'remote' && !values.pdf_parser?.remote_service_endpoint?.trim()) {
      message.error('远程模式必须填写远程解析服务地址')
      return
    }

    if (isSwitching) {
      if (!switchNotes) {
        message.error('切换部署位置前必须填写变更备注')
        return
      }

      Modal.confirm({
        title: '确认切换 MinerU 部署位置',
        content: `将从 ${currentTarget} 切换到 ${nextTarget}。这会影响后续所有文档解析，请确认目标服务已启动，并已准备好回滚方案。`,
        okText: '确认切换',
        cancelText: '取消',
        onOk: () => mutation.mutate(values),
      })
      return
    }

    mutation.mutate(values)
  }

  const parserSettings = data?.data?.pdf_parser
  const activeRuntimeStatus = parserSettings?.active_runtime_status

  const initialValues = data?.data

  useEffect(() => {
    if (data?.data) {
      form.setFieldsValue(data.data)
    }
  }, [data, form])

  if (isLoading) {
    return <div>加载中...</div>
  }

  const formatCheckTime = (value?: string) => {
    if (!value) return '-'
    return new Date(value).toLocaleString('zh-CN')
  }

  const getParserStatusTag = (status?: 'ready' | 'unavailable') => {
    if (status === 'ready') return <Tag color="green">可用</Tag>
    if (status === 'unavailable') return <Tag color="red">不可用</Tag>
    return <Tag>未知</Tag>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>系统配置</h2>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          onClick={() => form.submit()}
          loading={mutation.isLoading}
        >
          保存配置
        </Button>
      </div>

      <Form form={form} layout="vertical" onFinish={handleSubmit} initialValues={initialValues}>
        <Tabs activeKey={activeTab} onChange={setActiveTab}>
          <TabPane tab="问答 LLM" key="llm">
            <LlmConfigTab kind="llm" form={form} intro="该配置用于学生问答（RAG 增强回答与建议问题）" />
          </TabPane>

          <TabPane tab="题目结构 LLM" key="pdf-structure-llm">
            <LlmConfigTab kind="pdf_structure_llm" form={form} intro="该配置只用于题目抽取中跨页/跨列/选项缺失的 LLM 兜底修复" />
          </TabPane>

          <TabPane tab="大纲拆分 LLM" key="outline-llm">
            <LlmConfigTab kind="outline_llm" form={form} intro="该配置用于大纲 PDF 的四门课拆分与考察目标/章节树抽取" />
          </TabPane>

          <TabPane tab="文档元信息 LLM" key="doc-meta-llm">
            <LlmConfigTab kind="doc_meta_llm" form={form} intro="该配置用于从试卷/课本首页提取来源信息（年份/真题/机构/试卷名），规则未命中时兜底" />
          </TabPane>

          <TabPane tab="富化 LLM" key="enrich-llm">
            <LlmConfigTab kind="enrich_llm" form={form} intro="该配置用于审核通过后富化题目/知识点：生成答案与解析、标识所考知识点、生成知识点摘要" />
          </TabPane>

          <TabPane tab="向量化" key="embedding">
            <EmbeddingConfigTab form={form} />
          </TabPane>

          <TabPane tab="PDF解析器" key="pdf-parser">
            <Card>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
                message="解析器固定使用 MinerU"
                description="这里只配置 MinerU 的部署位置、服务地址、超时和处理窗口。切换本地或远程服务会影响后续所有文档解析。"
              />

              {activeRuntimeStatus && (
                <Alert
                  style={{ marginBottom: 16 }}
                  type={activeRuntimeStatus.health_status === 'ready' ? 'success' : 'error'}
                  showIcon
                  message={`MinerU 运行状态：${activeRuntimeStatus.deployment_target || parserSettings?.deployment_target}`}
                  description={
                    activeRuntimeStatus.error_detail
                      ? `${activeRuntimeStatus.error_detail}（服务地址：${activeRuntimeStatus.service_endpoint || '-'}，最近检查：${formatCheckTime(activeRuntimeStatus.checked_at)}）`
                      : `状态正常，服务地址：${activeRuntimeStatus.service_endpoint || '-'}，最近检查：${formatCheckTime(activeRuntimeStatus.checked_at)}`
                  }
                />
              )}

              <Form.Item label="解析引擎">
                <Space>
                  <strong>MinerU</strong>
                  {getParserStatusTag(activeRuntimeStatus?.health_status)}
                  {activeRuntimeStatus?.parser_version ? (
                    <Tag>{activeRuntimeStatus.parser_version}</Tag>
                  ) : null}
                </Space>
              </Form.Item>

              <Form.Item name={['pdf_parser', 'deployment_target']} label="部署位置">
                <Select>
                  <Option value="local">本地 Podman 服务</Option>
                  <Option value="remote">远程解析服务</Option>
                </Select>
              </Form.Item>

              <Form.Item
                name={['pdf_parser', 'local_service_endpoint']}
                label="本地解析服务地址"
                tooltip="默认指向本机 Podman 暴露端口；如 backend 也运行在容器中，可改为容器网络内地址"
              >
                <Input placeholder="http://localhost:8090" />
              </Form.Item>

              <Form.Item
                shouldUpdate={(prevValues, currentValues) =>
                  prevValues.pdf_parser?.deployment_target !== currentValues.pdf_parser?.deployment_target
                }
                noStyle
              >
                {({ getFieldValue }) =>
                  getFieldValue(['pdf_parser', 'deployment_target']) === 'remote' ? (
                    <Form.Item
                      name={['pdf_parser', 'remote_service_endpoint']}
                      label="远程解析服务地址"
                      tooltip="远程服务需实现 /health、/parse 和 /progress/{task_id} 接口"
                      rules={[{ required: true, message: '请选择远程模式时必须填写远程地址' }]}
                    >
                      <Input placeholder="https://parser.example.com" />
                    </Form.Item>
                  ) : null
                }
              </Form.Item>

              <Form.Item name={['pdf_parser', 'request_timeout_seconds']} label="解析请求超时（秒）">
                <InputNumber min={5} max={600} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item
                name={['pdf_parser', 'processing_window_size']}
                label="MinerU 处理窗口大小"
                tooltip="每次送入 MinerU 的页窗口大小。1 最稳，值越大吞吐越高但更吃内存。该值会随每次解析请求下发到本地解析服务。"
              >
                <InputNumber min={1} max={64} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item label="运行模式">
                <Input disabled value="MinerU 固定模式" />
              </Form.Item>

              <Form.Item
                name={['pdf_parser', 'service_switch_notes']}
                label="变更备注"
                tooltip="记录本次部署位置或服务地址变更的原因、步骤和回滚说明"
              >
                <TextArea rows={4} placeholder="例如：将 MinerU 解析服务迁移到远程 Linux 主机，已验证健康检查和回滚地址" />
              </Form.Item>
            </Card>

            <Card title="MinerU 配置变更历史" style={{ marginTop: 16 }}>
              <Table
                loading={historyLoading}
                dataSource={historyData?.data?.items || []}
                rowKey="id"
                pagination={false}
                size="small"
                locale={{ emptyText: '暂无配置变更记录' }}
              >
                <Table.Column
                  title="时间"
                  dataIndex="created_at"
                  key="created_at"
                  width={180}
                  render={(val: string) => val ? new Date(val).toLocaleString('zh-CN') : '-'}
                />
                <Table.Column title="旧解析器" dataIndex="old_parser" key="old_parser" width={120} />
                <Table.Column title="新解析器" dataIndex="new_parser" key="new_parser" width={120} />
                <Table.Column title="旧位置" dataIndex="old_target" key="old_target" width={100} />
                <Table.Column title="新位置" dataIndex="new_target" key="new_target" width={100} />
                <Table.Column title="备注" dataIndex="switch_notes" key="switch_notes" ellipsis />
                <Table.Column
                  title="操作人"
                  dataIndex="user_id"
                  key="user_id"
                  width={100}
                  render={(val: string | null) => val || 'System'}
                />
              </Table>
            </Card>
          </TabPane>
        </Tabs>
      </Form>
    </div>
  )
}

export default Settings
