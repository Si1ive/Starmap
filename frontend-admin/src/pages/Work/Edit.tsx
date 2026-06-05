import { useParams, useNavigate } from 'react-router-dom'
import {
  Form,
  Input,
  Select,
  DatePicker,
  Button,
  Card,
  message,
  InputNumber,
  Upload,
  Radio,
} from 'antd'
import { SaveOutlined, ArrowLeftOutlined, UploadOutlined, PlusOutlined, MinusCircleOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getWorkDetail, createWork, updateWork } from '@/api'
import type { Work } from '@/types'
import dayjs from 'dayjs'

const { TextArea } = Input
const { Option } = Select

const WorkEdit = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const isNew = !id || id === 'new'

  const { data, isLoading } = useQuery({
    queryKey: ['work', id],
    queryFn: () => getWorkDetail(id!),
    enabled: !isNew,
  })

  const mutation = useMutation({
    mutationFn: (values: Partial<Work>) => {
      if (isNew) {
        return createWork(values)
      }
      return updateWork(id!, values)
    },
    onSuccess: () => {
      message.success(isNew ? '创建成功' : '保存成功')
      queryClient.invalidateQueries({ queryKey: ['works'] })
      if (!isNew) {
        queryClient.invalidateQueries({ queryKey: ['work', id] })
      }
      navigate('/admin/works')
    },
    onError: () => {
      message.error(isNew ? '创建失败' : '保存失败')
    },
  })

  const handleSubmit = (values: any) => {
    const formattedValues = {
      ...values,
      release_date: values.release_date?.format('YYYY-MM-DD'),
    }
    mutation.mutate(formattedValues)
  }

  if (!isNew && isLoading) {
    return <div>加载中...</div>
  }

  const initialValues = isNew
    ? { type: 'movie', status: 'pending' }
    : {
        ...data?.data,
        release_date: data?.data?.release_date ? dayjs(data.data.release_date) : undefined,
      }

  const workType = Form.useWatch('type', form)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/works')}>
            返回
          </Button>
          <h2 style={{ margin: 0 }}>{isNew ? '新增作品' : '编辑作品'}</h2>
        </div>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          onClick={() => form.submit()}
          loading={mutation.isLoading}
        >
          保存
        </Button>
      </div>

      <Form form={form} layout="vertical" onFinish={handleSubmit} initialValues={initialValues}>
        <Card title="基本信息" style={{ marginBottom: 24 }}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="请输入作品标题" />
          </Form.Item>

          <Form.Item name="title_en" label="英文标题">
            <Input placeholder="请输入英文标题" />
          </Form.Item>

          <Form.Item name="cover" label="封面">
            <Upload listType="picture-card" maxCount={1}>
              <div>
                <UploadOutlined />
                <div style={{ marginTop: 8 }}>上传封面</div>
              </div>
            </Upload>
          </Form.Item>

          <Form.Item
            name="type"
            label="作品类型"
            rules={[{ required: true, message: '请选择作品类型' }]}
          >
            <Select placeholder="选择作品类型">
              <Option value="movie">电影</Option>
              <Option value="tv">电视剧</Option>
              <Option value="album">专辑</Option>
              <Option value="single">单曲</Option>
              <Option value="book">书籍</Option>
            </Select>
          </Form.Item>

          <Form.Item name="year" label="年份">
            <InputNumber min={1900} max={2100} style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item name="release_date" label="发行日期">
            <DatePicker style={{ width: '100%' }} placeholder="选择发行日期" />
          </Form.Item>

          <Form.Item name="rating" label="评分">
            <InputNumber min={0} max={10} step={0.1} style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item name="status" label="状态">
            <Radio.Group>
              <Radio value="complete">完整</Radio>
              <Radio value="partial">部分</Radio>
              <Radio value="pending">待审核</Radio>
            </Radio.Group>
          </Form.Item>

          <Form.Item name="genres" label="类型标签">
            <Select mode="tags" placeholder="添加类型标签" allowClear />
          </Form.Item>
        </Card>

        {/* 类型特有字段 */}
        {(workType === 'movie' || workType === 'tv') && (
          <Card title={workType === 'movie' ? '电影信息' : '电视剧信息'} style={{ marginBottom: 24 }}>
            <Form.Item name="director" label="导演">
              <Select mode="tags" placeholder="添加导演" allowClear />
            </Form.Item>
            <Form.Item name="actors" label="演员">
              <Select mode="tags" placeholder="添加演员" allowClear />
            </Form.Item>
            {workType === 'movie' && (
              <Form.Item name="box_office" label="票房（元）">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            )}
            {workType === 'tv' && (
              <>
                <Form.Item name="episodes" label="集数">
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
                <Form.Item name="platform" label="播出平台">
                  <Input placeholder="请输入播出平台" />
                </Form.Item>
              </>
            )}
          </Card>
        )}

        {(workType === 'album' || workType === 'single') && (
          <Card title="音乐信息" style={{ marginBottom: 24 }}>
            <Form.Item name="artist" label="歌手">
              <Select mode="tags" placeholder="添加歌手" allowClear />
            </Form.Item>
            {workType === 'album' && (
              <>
                <Form.Item name="record_company" label="唱片公司">
                  <Input placeholder="请输入唱片公司" />
                </Form.Item>
                <Form.List name="track_list">
                  {(fields, { add, remove }) => (
                    <>
                      {fields.map((field) => (
                        <Form.Item required={false} key={field.key}>
                          <Form.Item
                            {...field}
                            validateTrigger={['onChange', 'onBlur']}
                            noStyle
                          >
                            <Input placeholder="曲目名称" style={{ width: '60%' }} />
                          </Form.Item>
                          <MinusCircleOutlined
                            className="dynamic-delete-button"
                            onClick={() => remove(field.name)}
                          />
                        </Form.Item>
                      ))}
                      <Form.Item>
                        <Button type="dashed" onClick={() => add()} icon={<PlusOutlined />}>
                          添加曲目
                        </Button>
                      </Form.Item>
                    </>
                  )}
                </Form.List>
              </>
            )}
          </Card>
        )}

        {workType === 'book' && (
          <Card title="书籍信息" style={{ marginBottom: 24 }}>
            <Form.Item name="author" label="作者">
              <Select mode="tags" placeholder="添加作者" allowClear />
            </Form.Item>
            <Form.Item name="publisher" label="出版社">
              <Input placeholder="请输入出版社" />
            </Form.Item>
            <Form.Item name="isbn" label="ISBN">
              <Input placeholder="请输入ISBN" />
            </Form.Item>
          </Card>
        )}

        <Card title="描述信息" style={{ marginBottom: 24 }}>
          <Form.Item name="summary" label="摘要">
            <TextArea rows={3} placeholder="请输入作品摘要" />
          </Form.Item>
          <Form.Item name="description" label="详细描述">
            <TextArea rows={6} placeholder="请输入详细描述" />
          </Form.Item>
        </Card>

        <Card title="其他" style={{ marginBottom: 24 }}>
          <Form.Item name="tags" label="标签">
            <Select mode="tags" placeholder="添加标签" allowClear />
          </Form.Item>
        </Card>

        <div style={{ display: 'flex', justifyContent: 'center', gap: 16 }}>
          <Button onClick={() => navigate('/admin/works')}>取消</Button>
          <Button type="primary" onClick={() => form.submit()} loading={mutation.isLoading}>
            保存
          </Button>
        </div>
      </Form>
    </div>
  )
}

export default WorkEdit
