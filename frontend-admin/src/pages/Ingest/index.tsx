import { useState } from 'react'
import { Card, Table, Tag, Button, Modal, Form, Input, Select, Space, message, Progress } from 'antd'
import { PlusOutlined, FilePdfOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getSubjects, getChapters, ingestPdf, getIngestTasks } from '@/api'

const statusConfig: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '待执行' },
  running: { color: 'processing', text: '运行中' },
  completed: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
  stopped: { color: 'warning', text: '已停止' },
}

const PdfIngest = () => {
  const queryClient = useQueryClient()
  const [modalVisible, setModalVisible] = useState(false)
  const [form] = Form.useForm()
  const [selectedSubject, setSelectedSubject] = useState<string | undefined>()
  const [params, setParams] = useState({ page: 1, page_size: 20 })

  const { data: tasksData, isLoading } = useQuery({
    queryKey: ['ingestTasks', params],
    queryFn: () => getIngestTasks(params),
  })

  const { data: subjectsData } = useQuery({
    queryKey: ['subjects'],
    queryFn: getSubjects,
  })

  const { data: chaptersData } = useQuery({
    queryKey: ['chapters', selectedSubject],
    queryFn: () => getChapters(selectedSubject!),
    enabled: !!selectedSubject,
  })

  const tasks = tasksData?.data?.items || []
  const total = tasksData?.data?.total || 0
  const subjects = subjectsData?.data || []
  const chapters = chaptersData?.data || []

  const ingestMutation = useMutation({
    mutationFn: ingestPdf,
    onSuccess: (res) => {
      message.success(`PDF入库任务已创建: ${res.data?.task_id}`)
      setModalVisible(false)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['ingestTasks'] })
    },
  })

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      ingestMutation.mutate(values)
    })
  }

  const columns = [
    {
      title: '任务名称',
      dataIndex: 'name',
      width: 250,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: string) => {
        const config = statusConfig[s] || { color: 'default', text: s }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '进度',
      dataIndex: 'progress',
      width: 150,
      render: (progress: number, record: any) => (
        <Progress
          percent={Math.round(progress)}
          size="small"
          status={record.status === 'failed' ? 'exception' : record.status === 'completed' ? 'success' : 'active'}
        />
      ),
    },
    {
      title: '成功/失败',
      width: 100,
      render: (_: any, record: any) => (
        <span>
          <span style={{ color: '#52c41a' }}>{record.success_count || 0}</span>
          {' / '}
          <span style={{ color: '#ff4d4f' }}>{record.failed_count || 0}</span>
        </span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (t: string) => (t ? new Date(t).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '完成时间',
      dataIndex: 'completed_at',
      width: 180,
      render: (t: string) => (t ? new Date(t).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      ellipsis: true,
      render: (msg: string) => msg || '-',
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>PDF入库</h2>
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => queryClient.invalidateQueries({ queryKey: ['ingestTasks'] })}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setModalVisible(true)}
          >
            新增入库任务
          </Button>
        </Space>
      </div>

      <Card>
        <Table
          columns={columns}
          dataSource={tasks as any[]}
          rowKey="id"
          loading={isLoading}
          size="small"
          scroll={{ x: 1200 }}
          pagination={{
            current: params.page,
            pageSize: params.page_size,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
          }}
          onChange={(pagination) =>
            setParams((prev) => ({
              ...prev,
              page: pagination.current || 1,
              page_size: pagination.pageSize || 20,
            }))
          }
        />
      </Card>

      <Modal
        title="新增PDF入库任务"
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => {
          setModalVisible(false)
          form.resetFields()
        }}
        confirmLoading={ingestMutation.isPending}
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="pdf_path"
            label="PDF文件路径"
            rules={[{ required: true, message: '请输入PDF文件路径' }]}
            tooltip="服务器上的PDF文件绝对路径，如 /data/books/王道数据结构2025.pdf"
          >
            <Input
              placeholder="/data/books/王道数据结构2025.pdf"
              prefix={<FilePdfOutlined />}
            />
          </Form.Item>
          <Form.Item
            name="subject_id"
            label="学科"
            rules={[{ required: true, message: '请选择学科' }]}
          >
            <Select
              placeholder="选择学科"
              onChange={(value) => {
                setSelectedSubject(value)
                form.setFieldValue('chapter_id', undefined)
              }}
              options={subjects.map((s) => ({ label: s.name, value: s.id }))}
            />
          </Form.Item>
          <Form.Item
            name="chapter_id"
            label="章节"
            rules={[{ required: true, message: '请选择章节' }]}
          >
            <Select
              placeholder="选择章节"
              disabled={!selectedSubject}
              options={chapters.map((c) => ({ label: c.name, value: c.id }))}
            />
          </Form.Item>
          <Form.Item name="source" label="来源说明">
            <Input placeholder="如：王道2025/数据结构" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default PdfIngest
