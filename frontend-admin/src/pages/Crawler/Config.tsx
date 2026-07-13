import { useEffect, useMemo } from 'react'
import { Card, Form, Input, Select, Switch, InputNumber, Button, message, Row, Col } from 'antd'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getSettings, updateSettings } from '@/api'

const CrawlerConfig = () => {
  const queryClient = useQueryClient()
  const [form] = Form.useForm()

  const { data } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
  })

  const updateMutation = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      message.success('配置已保存')
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: () => {
      message.error('保存失败')
    },
  })

  const settings = useMemo(
    () => (((data?.data as any)?.crawler) || {}) as Record<string, any>,
    [data?.data],
  )

  useEffect(() => {
    form.setFieldsValue({
      max_concurrent: settings.max_concurrent,
      request_delay: settings.request_delay,
      request_timeout: settings.request_timeout,
      max_retries: settings.max_retries,
      retry_delay: settings.retry_delay,
      user_agent: settings.user_agent,
      proxy_enabled: settings.proxy_enabled,
      proxy_url: settings.proxy_url,
      respect_robots_txt: settings.respect_robots_txt,
      auto_detect_encoding: settings.auto_detect_encoding,
      follow_redirects: settings.follow_redirects,
      max_redirects: settings.max_redirects,
      max_depth: settings.max_depth,
      dedup_enabled: settings.dedup_enabled,
      storage_batch_size: settings.storage_batch_size,
      log_level: settings.log_level,
      data_sources: settings.data_sources,
    })
  }, [form, settings])

  const handleSave = () => {
    form.validateFields().then((values) => {
      const currentSettings = data?.data || {}
      updateMutation.mutate({
        ...currentSettings,
        crawler: {
          ...settings,
          ...values,
        },
      } as any)
    })
  }

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>爬虫配置</h2>

      <Form
        form={form}
        layout="vertical"
        initialValues={{
          // 基础配置
          max_concurrent: settings.max_concurrent,
          request_delay: settings.request_delay,
          request_timeout: settings.request_timeout,
          max_retries: settings.max_retries,
          retry_delay: settings.retry_delay,
          user_agent: settings.user_agent,
          proxy_enabled: settings.proxy_enabled,
          proxy_url: settings.proxy_url,
          // 高级配置
          respect_robots_txt: settings.respect_robots_txt,
          auto_detect_encoding: settings.auto_detect_encoding,
          follow_redirects: settings.follow_redirects,
          max_redirects: settings.max_redirects,
          max_depth: settings.max_depth,
          dedup_enabled: settings.dedup_enabled,
          storage_batch_size: settings.storage_batch_size,
          log_level: settings.log_level,
        }}
      >
        {/* 基础配置 */}
        <Card title="基础配置" style={{ marginBottom: 24 }}>
          <Row gutter={24}>
            <Col xs={24} md={8}>
              <Form.Item label="最大并发数" name="max_concurrent" tooltip="同时运行的爬虫任务数量">
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="请求间隔(秒)" name="request_delay" tooltip="两次请求之间的最小间隔">
                <InputNumber min={0} max={60} step={0.5} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="请求超时(秒)" name="request_timeout">
                <InputNumber min={5} max={120} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={24}>
            <Col xs={24} md={8}>
              <Form.Item label="最大重试次数" name="max_retries">
                <InputNumber min={0} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="重试间隔(秒)" name="retry_delay">
                <InputNumber min={1} max={60} step={0.5} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="User-Agent" name="user_agent">
                <Input placeholder="408-Platform/1.0" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={24}>
            <Col xs={24} md={8}>
              <Form.Item label="启用代理" name="proxy_enabled" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col xs={24} md={16}>
              <Form.Item label="代理地址" name="proxy_url">
                <Input placeholder="socks5://127.0.0.1:1080" disabled={false} />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        {/* 高级配置 */}
        <Card title="高级配置" style={{ marginBottom: 24 }}>
          <Row gutter={24}>
            <Col xs={24} md={8}>
              <Form.Item label="遵守 robots.txt" name="respect_robots_txt" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="自动检测编码" name="auto_detect_encoding" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="跟随重定向" name="follow_redirects" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={24}>
            <Col xs={24} md={8}>
              <Form.Item label="最大重定向次数" name="max_redirects">
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="最大爬取深度" name="max_depth" tooltip="限制爬取链接的最大层级">
                <InputNumber min={1} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="日志级别" name="log_level">
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
          <Row gutter={24}>
            <Col xs={24} md={8}>
              <Form.Item label="去重" name="dedup_enabled" valuePropName="checked" tooltip="基于 URL 去重避免重复爬取">
                <Switch />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="存储批量大小" name="storage_batch_size" tooltip="写入数据库时的批量大小">
                <InputNumber min={10} max={1000} step={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        {/* 数据源配置 */}
        <Card title="数据源配置" style={{ marginBottom: 24 }}>
          <Form.List name="data_sources" initialValue={[
            { name: '维基百科', url: 'https://zh.wikipedia.org', enabled: true, priority: 1 },
            { name: '豆瓣', url: 'https://www.douban.com', enabled: true, priority: 2 },
          ]}>
            {(fields, { add, remove }) => (
              <>
                {fields.map(({ key, name, ...restField }) => (
                  <Row key={key} gutter={16} align="middle" style={{ marginBottom: 12 }}>
                    <Col span={5}>
                      <Form.Item {...restField} name={[name, 'name']} rules={[{ required: true, message: '请输入名称' }]}>
                        <Input placeholder="数据源名称" />
                      </Form.Item>
                    </Col>
                    <Col span={9}>
                      <Form.Item {...restField} name={[name, 'url']} rules={[{ required: true, message: '请输入URL' }]}>
                        <Input placeholder="https://example.com" />
                      </Form.Item>
                    </Col>
                    <Col span={4}>
                      <Form.Item {...restField} name={[name, 'priority']}>
                        <InputNumber min={1} max={10} style={{ width: '100%' }} placeholder="优先级" />
                      </Form.Item>
                    </Col>
                    <Col span={3}>
                      <Form.Item {...restField} name={[name, 'enabled']} valuePropName="checked">
                        <Switch />
                      </Form.Item>
                    </Col>
                    <Col span={3}>
                      <Button danger type="link" onClick={() => remove(name)}>
                        删除
                      </Button>
                    </Col>
                  </Row>
                ))}
                <Button type="dashed" onClick={() => add()} block>
                  + 添加数据源
                </Button>
              </>
            )}
          </Form.List>
        </Card>

        <div style={{ textAlign: 'right' }}>
          <Button
            type="primary"
            size="large"
            onClick={handleSave}
            loading={updateMutation.isPending}
          >
            保存配置
          </Button>
        </div>
      </Form>
    </div>
  )
}

export default CrawlerConfig
