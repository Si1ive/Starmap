import { useEffect } from 'react'
import { SaveOutlined } from '@ant-design/icons'
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Switch,
  message,
} from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getCrawlerConfig,
  updateCrawlerConfig,
  type CrawlerRuntimeConfig,
} from '@/api'

const CrawlerConfig = () => {
  const queryClient = useQueryClient()
  const [form] = Form.useForm<CrawlerRuntimeConfig>()
  const rotateUserAgent = Form.useWatch('rotate_user_agent', form)
  const proxyEnabled = Form.useWatch('proxy_enabled', form)
  const followRedirects = Form.useWatch('follow_redirects', form)

  const { data, isLoading } = useQuery({
    queryKey: ['crawler-config'],
    queryFn: getCrawlerConfig,
  })

  useEffect(() => {
    if (data?.data) {
      form.setFieldsValue(data.data)
    }
  }, [data?.data, form])

  const updateMutation = useMutation({
    mutationFn: updateCrawlerConfig,
    onSuccess: (response) => {
      form.setFieldsValue(response.data)
      message.success('配置已保存')
      queryClient.invalidateQueries({ queryKey: ['crawler-config'] })
    },
    onError: () => {
      message.error('保存失败，请检查配置后重试')
    },
  })

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>爬虫配置</h2>

      <Form<CrawlerRuntimeConfig>
        form={form}
        layout="vertical"
        onFinish={(values) => updateMutation.mutate(values)}
      >
        <Card title="请求与执行" loading={isLoading} style={{ marginBottom: 24 }}>
          <Row gutter={24}>
            <Col xs={24} md={12} xl={6}>
              <Form.Item
                label="请求并发数"
                name="concurrent_requests"
                tooltip="单个爬虫任务允许同时发出的最大请求数"
                rules={[{ required: true }]}
              >
                <InputNumber min={1} max={64} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12} xl={6}>
              <Form.Item
                label="单域名并发数"
                name="concurrent_requests_per_domain"
                tooltip="同一域名允许同时发出的最大请求数，不得超过请求并发数"
                rules={[{ required: true }]}
              >
                <InputNumber min={1} max={64} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12} xl={6}>
              <Form.Item
                label="请求间隔（秒）"
                name="download_delay_seconds"
                rules={[{ required: true }]}
              >
                <InputNumber min={0} max={60} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12} xl={6}>
              <Form.Item
                label="请求超时（秒）"
                name="request_timeout_seconds"
                rules={[{ required: true }]}
              >
                <InputNumber min={5} max={600} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={24}>
            <Col xs={24} md={12} xl={6}>
              <Form.Item
                label="最大重试次数"
                name="retry_times"
                rules={[{ required: true }]}
              >
                <InputNumber min={0} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12} xl={6}>
              <Form.Item
                label="最大爬取深度"
                name="max_depth"
                rules={[{ required: true }]}
              >
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12} xl={6}>
              <Form.Item
                label="日志级别"
                name="log_level"
                rules={[{ required: true }]}
              >
                <Select
                  options={[
                    { label: 'DEBUG', value: 'DEBUG' },
                    { label: 'INFO', value: 'INFO' },
                    { label: 'WARNING', value: 'WARNING' },
                    { label: 'ERROR', value: 'ERROR' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        <Card title="网络策略" loading={isLoading} style={{ marginBottom: 24 }}>
          <Row gutter={24}>
            <Col xs={24} md={8}>
              <Form.Item
                label="遵守 robots.txt"
                name="obey_robots_txt"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                label="跟随重定向"
                name="follow_redirects"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                label="最大重定向次数"
                name="max_redirect_times"
                rules={[{ required: true }]}
              >
                <InputNumber
                  min={0}
                  max={50}
                  disabled={!followRedirects}
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={24}>
            <Col xs={24} md={8}>
              <Form.Item
                label="随机 User-Agent"
                name="rotate_user_agent"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
            </Col>
            <Col xs={24} md={16}>
              <Form.Item
                label="固定 User-Agent"
                name="user_agent"
                dependencies={['rotate_user_agent']}
                rules={[
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (getFieldValue('rotate_user_agent') || value?.trim()) {
                        return Promise.resolve()
                      }
                      return Promise.reject(new Error('关闭随机 User-Agent 后必须填写'))
                    },
                  }),
                ]}
              >
                <Input disabled={rotateUserAgent} placeholder="408StudyBot/1.0" />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={24}>
            <Col xs={24} md={8}>
              <Form.Item
                label="启用 HTTP 代理"
                name="proxy_enabled"
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
            </Col>
            <Col xs={24} md={16}>
              <Form.Item
                label="代理地址"
                name="proxy_url"
                dependencies={['proxy_enabled']}
                rules={[
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!getFieldValue('proxy_enabled')) {
                        return Promise.resolve()
                      }
                      if (/^https?:\/\/[^/]+/i.test(value || '')) {
                        return Promise.resolve()
                      }
                      return Promise.reject(new Error('请输入有效的 HTTP 或 HTTPS 代理地址'))
                    },
                  }),
                ]}
              >
                <Input
                  disabled={!proxyEnabled}
                  placeholder="http://127.0.0.1:7890"
                />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        <div style={{ textAlign: 'right' }}>
          <Button
            type="primary"
            htmlType="submit"
            icon={<SaveOutlined />}
            loading={updateMutation.isPending}
            disabled={isLoading}
          >
            保存配置
          </Button>
        </div>
      </Form>
    </div>
  )
}

export default CrawlerConfig
