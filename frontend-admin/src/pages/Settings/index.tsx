import { useEffect, useState } from 'react'
import { Alert, Form, Input, InputNumber, Select, Switch, Button, Card, message, Tabs, Tag, Space, Table, Modal } from 'antd'
import { SaveOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getSettings,
  updateSettings,
  getPdfParserHistory,
  getPdfStructureLlmStatus,
  testPdfStructureLlm,
} from '@/api'
import type { SystemSettings } from '@/api/settings'

const { TextArea } = Input
const { Option } = Select
const { TabPane } = Tabs

const Settings = () => {
  const [form] = Form.useForm()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState('llm')

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
  })

  const mutation = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      message.success('保存成功')
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      queryClient.invalidateQueries({ queryKey: ['pdf-parser-history'] })
    },
    onError: () => {
      message.error('保存失败')
    },
  })

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['pdf-parser-history'],
    queryFn: () => getPdfParserHistory(1, 20),
  })

  const { data: pdfStructureLlmStatusData, isLoading: pdfStructureLlmStatusLoading } = useQuery({
    queryKey: ['pdf-structure-llm-status'],
    queryFn: getPdfStructureLlmStatus,
  })

  const testPdfStructureLlmMutation = useMutation({
    mutationFn: testPdfStructureLlm,
    onSuccess: (res) => {
      if (res.code === 200 && res.data?.success) {
        message.success(`测试成功：${res.data.reply || '已连通'}`)
        queryClient.invalidateQueries({ queryKey: ['pdf-structure-llm-status'] })
      } else {
        message.error(res.data?.error || res.message || '测试失败')
      }
    },
    onError: () => {
      message.error('测试失败')
    },
  })

  const handleSubmit = (values: Partial<SystemSettings>) => {
    const nextParser = values.pdf_parser?.active_parser
    const currentParser = parserSettings?.active_parser
    const nextTarget = values.pdf_parser?.deployment_target
    const currentTarget = parserSettings?.deployment_target
    const switchNotes = values.pdf_parser?.service_switch_notes?.trim() || ''
    const isSwitching =
      (!!nextParser && !!currentParser && nextParser !== currentParser) ||
      (!!nextTarget && !!currentTarget && nextTarget !== currentTarget)

    if (nextTarget === 'remote' && !values.pdf_parser?.remote_service_endpoint?.trim()) {
      message.error('远程模式必须填写远程解析服务地址')
      return
    }

    if (isSwitching) {
      const targetStatus = availableParsers.find((item) => item.parser_name === nextParser)
      if (!switchNotes) {
        message.error('切换解析器前必须填写切换备注')
        return
      }
      if (nextTarget === 'local' && (!targetStatus || targetStatus.health_status !== 'ready')) {
        message.error(`目标解析器 ${nextParser} 当前不可用，请先完成停旧启新和依赖校验`)
        return
      }

      Modal.confirm({
        title: '确认切换系统级 PDF 解析配置',
        content: `将从 ${currentParser}/${currentTarget} 切换到 ${nextParser}/${nextTarget}。这会影响后续所有文档解析，请确认旧服务已下线、新服务已启动，并已准备好回滚方案。`,
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
  const availableParsers = parserSettings?.available_parsers || []
  const pdfStructureLlmStatus = pdfStructureLlmStatusData?.data

  const initialValues = data?.data || {
    llm: {
      model: 'gpt-4',
      temperature: 0.7,
      max_tokens: 2000,
      system_prompt: '',
    },
    pdf_structure_llm: {
      enabled: false,
      provider: 'openai_compatible',
      base_url: '',
      api_key: '',
      model: 'gpt-4',
      temperature: 0.1,
      max_tokens: 2000,
      timeout_seconds: 60,
      system_prompt: '你是一个PDF题目结构分析专家，负责判断跨页、跨列导致的题目拆分和选项缺失问题。',
    },
    search: {
      default_page_size: 20,
      max_results: 100,
      similarity_threshold: 0.8,
      weights: {
        name: 1.0,
        category: 0.8,
        relation: 0.6,
      },
      cache_ttl: 300,
    },
    crawler: {
      request_interval: 1.0,
      max_concurrency: 5,
      timeout: 30,
      user_agents: [],
      max_concurrent: 5,
      request_delay: 1.0,
      request_timeout: 30,
      max_retries: 3,
      retry_delay: 2.0,
      user_agent: '408-Platform/1.0',
      proxy_enabled: false,
      proxy_url: '',
      respect_robots_txt: true,
      auto_detect_encoding: true,
      follow_redirects: true,
      max_redirects: 5,
      max_depth: 3,
      dedup_enabled: true,
      storage_batch_size: 100,
      log_level: 'INFO',
      data_sources: [],
      proxy: '',
    },
    system: {
      name: '408考研学习平台',
      maintenance_mode: false,
      log_level: 'INFO',
    },
    pdf_parser: {
      active_parser: 'mineru',
      service_mode: 'single_active',
      service_switch_notes: '',
      deployment_target: 'local',
      local_service_endpoint: 'http://localhost:8090',
      remote_service_endpoint: '',
      request_timeout_seconds: 600,
      processing_window_size: 1,
    },
  }

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
          <TabPane tab="LLM配置" key="llm">
            <Card>
              <Form.Item name={['llm', 'model']} label="模型选择">
                <Select>
                  <Option value="gpt-4">GPT-4</Option>
                  <Option value="gpt-3.5-turbo">GPT-3.5 Turbo</Option>
                </Select>
              </Form.Item>

              <Form.Item name={['llm', 'temperature']} label="温度参数">
                <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['llm', 'max_tokens']} label="最大Token数">
                <InputNumber min={100} max={8000} step={100} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['llm', 'system_prompt']} label="系统提示词">
                <TextArea rows={4} placeholder="输入系统提示词" />
              </Form.Item>
            </Card>
          </TabPane>

          <TabPane tab="PDF结构LLM" key="pdf-structure-llm">
            <Card>
              <div
                style={{
                  display: 'flex',
                  gap: 12,
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  marginBottom: 16,
                  flexWrap: 'wrap',
                }}
              >
                <Alert
                  type={pdfStructureLlmStatus?.is_available ? 'success' : 'info'}
                  showIcon
                  style={{ flex: 1, minWidth: 280 }}
                  message="该配置只用于 PDF 文档结构解析"
                  description={
                    pdfStructureLlmStatusLoading
                      ? '正在读取后端配置状态...'
                      : pdfStructureLlmStatus?.is_available
                        ? `当前可用：${pdfStructureLlmStatus.model}，API Key 来源：${pdfStructureLlmStatus.uses_env_api_key ? '环境变量' : '配置中心'}`
                        : (pdfStructureLlmStatus?.issues?.join('；') || '题目抽取中的复杂跨页、跨列、选项缺失场景会使用这里的 LLM 兜底；聊天、检索问答等后续功能仍使用独立配置。')
                  }
                />
                <Button
                  icon={<ThunderboltOutlined />}
                  loading={testPdfStructureLlmMutation.isLoading}
                  onClick={() => {
                    const current = form.getFieldValue('pdf_structure_llm') || {}
                    testPdfStructureLlmMutation.mutate(current)
                  }}
                >
                  测试当前配置
                </Button>
              </div>

              <Form.Item name={['pdf_structure_llm', 'enabled']} label="启用LLM兜底" valuePropName="checked">
                <Switch />
              </Form.Item>

              <Form.Item name={['pdf_structure_llm', 'provider']} label="服务类型">
                <Select>
                  <Option value="openai_compatible">OpenAI 兼容接口</Option>
                </Select>
              </Form.Item>

              <Form.Item
                name={['pdf_structure_llm', 'base_url']}
                label="Base URL"
                tooltip="OpenAI 官方接口可留空；兼容服务填写类似 https://api.example.com/v1"
              >
                <Input placeholder="https://api.openai.com/v1" />
              </Form.Item>

              <Form.Item
                name={['pdf_structure_llm', 'api_key']}
                label="API Key"
                tooltip="留空时后端使用 OPENAI_API_KEY 环境变量"
              >
                <Input.Password placeholder="留空使用环境变量；已保存密钥会显示为保留占位符" autoComplete="new-password" />
              </Form.Item>

              <Form.Item name={['pdf_structure_llm', 'model']} label="模型">
                <Input placeholder="gpt-4o-mini" />
              </Form.Item>

              <Form.Item name={['pdf_structure_llm', 'temperature']} label="温度参数">
                <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['pdf_structure_llm', 'max_tokens']} label="最大Token数">
                <InputNumber min={100} max={8000} step={100} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['pdf_structure_llm', 'timeout_seconds']} label="请求超时（秒）">
                <InputNumber min={5} max={300} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['pdf_structure_llm', 'system_prompt']} label="系统提示词">
                <TextArea rows={4} placeholder="输入 PDF 结构解析专用系统提示词" />
              </Form.Item>
            </Card>
          </TabPane>

          <TabPane tab="搜索配置" key="search">
            <Card>
              <Form.Item name={['search', 'default_page_size']} label="默认分页大小">
                <InputNumber min={10} max={100} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['search', 'max_results']} label="最大返回结果数">
                <InputNumber min={10} max={500} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['search', 'similarity_threshold']} label="相似度阈值">
                <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['search', 'cache_ttl']} label="缓存TTL（秒）">
                <InputNumber min={60} max={3600} style={{ width: '100%' }} />
              </Form.Item>
            </Card>
          </TabPane>

          <TabPane tab="爬虫配置" key="crawler">
            <Card>
              <Form.Item name={['crawler', 'request_interval']} label="请求间隔（秒）">
                <InputNumber min={0.5} max={10} step={0.5} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['crawler', 'max_concurrency']} label="最大并发数">
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['crawler', 'timeout']} label="超时时间（秒）">
                <InputNumber min={5} max={120} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['crawler', 'proxy']} label="代理服务器">
                <Input placeholder="http://proxy.example.com:8080" />
              </Form.Item>
            </Card>
          </TabPane>

          <TabPane tab="系统设置" key="system">
            <Card>
              <Form.Item name={['system', 'name']} label="系统名称">
                <Input />
              </Form.Item>

              <Form.Item name={['system', 'announcement']} label="公告内容">
                <TextArea rows={3} placeholder="输入系统公告" />
              </Form.Item>

              <Form.Item name={['system', 'maintenance_mode']} label="维护模式" valuePropName="checked">
                <Switch />
              </Form.Item>

              <Form.Item name={['system', 'log_level']} label="日志级别">
                <Select>
                  <Option value="DEBUG">DEBUG</Option>
                  <Option value="INFO">INFO</Option>
                  <Option value="WARNING">WARNING</Option>
                  <Option value="ERROR">ERROR</Option>
                </Select>
              </Form.Item>
            </Card>
          </TabPane>

          <TabPane tab="PDF解析器" key="pdf-parser">
            <Card>
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message="这是系统级切换，不是单文件参数"
                description="切换 PDF 解析器或服务部署位置意味着你要停掉当前服务、下线原实现，再启用新的解析服务。同一时间只允许一个解析器处于激活状态。"
              />

              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
                message="推荐策略：默认使用 MinerU + 本地 Podman 服务"
                description="MinerU 更适合作为当前项目的主流默认方案；Docling 保留为高性能备选。本地模式默认访问本机 Podman 中的解析服务；远程模式当前先保留配置扩展口。"
              />

              {activeRuntimeStatus && (
                <Alert
                  style={{ marginBottom: 16 }}
                  type={activeRuntimeStatus.health_status === 'ready' ? 'success' : 'error'}
                  showIcon
                  message={`当前激活解析器运行状态：${activeRuntimeStatus.parser_name} / ${activeRuntimeStatus.deployment_target || parserSettings?.deployment_target}`}
                  description={
                    activeRuntimeStatus.error_detail
                      ? `${activeRuntimeStatus.error_detail}（服务地址：${activeRuntimeStatus.service_endpoint || '-'}，最近检查：${formatCheckTime(activeRuntimeStatus.checked_at)}）`
                      : `状态正常，服务地址：${activeRuntimeStatus.service_endpoint || '-'}，最近检查：${formatCheckTime(activeRuntimeStatus.checked_at)}`
                  }
                />
              )}

              <div style={{ marginBottom: 16 }}>
                {availableParsers.map((item) => (
                  <div
                    key={item.parser_name}
                    style={{
                      border: '1px solid #f0f0f0',
                      borderRadius: 8,
                      padding: 12,
                      marginBottom: 8,
                    }}
                  >
                    <Space wrap>
                      <strong>{item.parser_name}</strong>
                      <Tag>{item.parser_version}</Tag>
                      <Tag>{item.deployment_target === 'remote' ? '远程' : '本地'}</Tag>
                      {getParserStatusTag(item.health_status)}
                      {item.is_active ? <Tag color="blue">当前激活</Tag> : null}
                    </Space>
                    <div style={{ marginTop: 8, color: '#666' }}>
                      服务地址：{item.service_endpoint || '-'}
                    </div>
                    <div style={{ marginTop: 4, color: '#666' }}>
                      最近检查：{formatCheckTime(item.checked_at)}
                    </div>
                    {item.error_detail ? (
                      <div style={{ marginTop: 6, color: '#cf1322' }}>{item.error_detail}</div>
                    ) : null}
                  </div>
                ))}
              </div>

              <Form.Item name={['pdf_parser', 'active_parser']} label="当前激活解析器">
                <Select>
                  <Option value="mineru">MinerU（推荐默认）</Option>
                  <Option value="docling">Docling（性能优先）</Option>
                </Select>
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
                      rules={[{ required: true, message: '请选择远程模式时必须填写远程地址' }]}
                    >
                      <Input placeholder="https://parser.example.com" />
                    </Form.Item>
                  ) : null
                }
              </Form.Item>

              <Form.Item
                name={['pdf_parser', 'request_timeout_seconds']}
                label="解析请求超时（秒）"
              >
                <InputNumber min={5} max={600} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item
                name={['pdf_parser', 'processing_window_size']}
                label="MinerU 处理窗口大小"
                tooltip="每次送入 MinerU 的页窗口大小。1 最稳，值越大吞吐越高但更吃内存。该值会随每次解析请求下发到本地解析服务。"
              >
                <InputNumber min={1} max={64} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name={['pdf_parser', 'service_mode']} label="运行模式">
                <Input disabled />
              </Form.Item>

              <Form.Item
                name={['pdf_parser', 'service_switch_notes']}
                label="切换备注"
                tooltip="记录本次服务切换的原因、依赖变更、安装步骤或回滚说明"
              >
                <TextArea rows={4} placeholder="例如：已停用 Docling 容器，切换为 MinerU OCR 服务，等待重建解析镜像" />
              </Form.Item>
            </Card>

            <Card title="切换历史" style={{ marginTop: 16 }}>
              <Table
                loading={historyLoading}
                dataSource={historyData?.data?.items || []}
                rowKey="id"
                pagination={false}
                size="small"
                locale={{ emptyText: '暂无切换记录' }}
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
