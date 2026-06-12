import { useState } from 'react'
import { Alert, Form, Input, InputNumber, Select, Switch, Button, Card, message, Tabs } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getSettings, updateSettings } from '@/api'
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
    },
    onError: () => {
      message.error('保存失败')
    },
  })

  const handleSubmit = (values: Partial<SystemSettings>) => {
    mutation.mutate(values)
  }

  const initialValues = data?.data || {
    llm: {
      model: 'gpt-4',
      temperature: 0.7,
      max_tokens: 2000,
      system_prompt: '',
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
    },
    system: {
      name: 'StarMap',
      maintenance_mode: false,
      log_level: 'INFO',
    },
    pdf_parser: {
      active_parser: 'docling',
      service_mode: 'single_active',
      service_switch_notes: '',
    },
  }

  if (isLoading) {
    return <div>加载中...</div>
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
                description="切换 PDF 解析器意味着你要停掉当前服务、卸载或下线原实现，再注册并启用新的解析服务。同一时间只允许一个解析器处于激活状态。"
              />

              <Form.Item name={['pdf_parser', 'active_parser']} label="当前激活解析器">
                <Select>
                  <Option value="docling">Docling</Option>
                  <Option value="mineru">MinerU</Option>
                </Select>
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
          </TabPane>
        </Tabs>
      </Form>
    </div>
  )
}

export default Settings
