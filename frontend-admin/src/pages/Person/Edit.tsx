import { useParams, useNavigate } from 'react-router-dom'
import { Form, Input, Select, DatePicker, Button, Card, message, Radio, Upload } from 'antd'
import { SaveOutlined, ArrowLeftOutlined, UploadOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getPersonDetail, createPerson, updatePerson } from '@/api'
import type { Person } from '@/types'
import dayjs from 'dayjs'

const { TextArea } = Input
const { Option } = Select

const PersonEdit = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const isNew = !id || id === 'new'

  const { data, isLoading } = useQuery({
    queryKey: ['person', id],
    queryFn: () => getPersonDetail(id!),
    enabled: !isNew,
  })

  const mutation = useMutation({
    mutationFn: (values: Partial<Person>) => {
      if (isNew) {
        return createPerson(values)
      }
      return updatePerson(id!, values)
    },
    onSuccess: () => {
      message.success(isNew ? '创建成功' : '保存成功')
      queryClient.invalidateQueries({ queryKey: ['persons'] })
      if (!isNew) {
        queryClient.invalidateQueries({ queryKey: ['person', id] })
      }
      navigate('/admin/persons')
    },
    onError: () => {
      message.error(isNew ? '创建失败' : '保存失败')
    },
  })

  const handleSubmit = (values: any) => {
    const formattedValues = {
      ...values,
      birth_date: values.birth_date?.format('YYYY-MM-DD'),
    }
    mutation.mutate(formattedValues)
  }

  if (!isNew && isLoading) {
    return <div>加载中...</div>
  }

  const initialValues = isNew
    ? {}
    : {
        ...data?.data,
        birth_date: data?.data?.birth_date ? dayjs(data.data.birth_date) : undefined,
      }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/persons')}>
            返回
          </Button>
          <h2 style={{ margin: 0 }}>{isNew ? '新增艺人' : '编辑艺人'}</h2>
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

      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        initialValues={initialValues}
      >
        <Card title="基本信息" style={{ marginBottom: 24 }}>
          <Form.Item
            name="name"
            label="姓名"
            rules={[{ required: true, message: '请输入姓名' }]}
          >
            <Input placeholder="请输入姓名" />
          </Form.Item>

          <Form.Item name="name_en" label="英文名">
            <Input placeholder="请输入英文名" />
          </Form.Item>

          <Form.Item name="avatar" label="头像">
            <Upload listType="picture-card" maxCount={1}>
              <div>
                <UploadOutlined />
                <div style={{ marginTop: 8 }}>上传头像</div>
              </div>
            </Upload>
          </Form.Item>

          <Form.Item name="gender" label="性别">
            <Radio.Group>
              <Radio value="male">男</Radio>
              <Radio value="female">女</Radio>
              <Radio value="unknown">未知</Radio>
            </Radio.Group>
          </Form.Item>

          <Form.Item name="birth_date" label="出生日期">
            <DatePicker style={{ width: '100%' }} placeholder="选择出生日期" />
          </Form.Item>

          <Form.Item name="birth_place" label="出生地点">
            <Input placeholder="请输入出生地点" />
          </Form.Item>

          <Form.Item name="nationality" label="国籍">
            <Select placeholder="选择国籍" allowClear>
              <Option value="中国">中国</Option>
              <Option value="美国">美国</Option>
              <Option value="日本">日本</Option>
              <Option value="韩国">韩国</Option>
              <Option value="英国">英国</Option>
              <Option value="其他">其他</Option>
            </Select>
          </Form.Item>

          <Form.Item name="height" label="身高 (cm)">
            <Input type="number" placeholder="请输入身高" />
          </Form.Item>

          <Form.Item name="categories" label="职业分类">
            <Select mode="multiple" placeholder="选择职业分类">
              <Option value="actor">演员</Option>
              <Option value="singer">歌手</Option>
              <Option value="director">导演</Option>
              <Option value="producer">制片人</Option>
              <Option value="writer">编剧</Option>
              <Option value="composer">作曲</Option>
            </Select>
          </Form.Item>
        </Card>

        <Card title="详细信息" style={{ marginBottom: 24 }}>
          <Form.Item name="summary" label="摘要">
            <TextArea rows={3} placeholder="请输入人物摘要" />
          </Form.Item>

          <Form.Item name="biography" label="详细传记">
            <TextArea rows={6} placeholder="请输入详细传记" />
          </Form.Item>
        </Card>

        <Card title="扩展信息" style={{ marginBottom: 24 }}>
          <Form.Item name="works" label="代表作品">
            <Select mode="multiple" placeholder="选择代表作品" allowClear>
              <Option value="work_1">作品1</Option>
              <Option value="work_2">作品2</Option>
            </Select>
          </Form.Item>

          <Form.Item name="tags" label="标签">
            <Select mode="tags" placeholder="添加标签" allowClear />
          </Form.Item>
        </Card>

        <div style={{ display: 'flex', justifyContent: 'center', gap: 16 }}>
          <Button onClick={() => navigate('/admin/persons')}>取消</Button>
          <Button type="primary" onClick={() => form.submit()} loading={mutation.isLoading}>
            保存
          </Button>
        </div>
      </Form>
    </div>
  )
}

export default PersonEdit
