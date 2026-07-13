import { useEffect, useMemo, useState } from 'react'
import { Button, Descriptions, Drawer, Input, Select, Space, Tag } from 'antd'
import { CheckOutlined, CloseOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { getCanonicalChapters } from '@/api/corpus'

const { TextArea } = Input

export type ReviewStatus = 'pending' | 'approved' | 'rejected'

const reviewStatusConfig: Record<ReviewStatus, { color: string; text: string }> = {
  pending: { color: 'orange', text: '待人工核验' },
  approved: { color: 'green', text: '已通过' },
  rejected: { color: 'red', text: '未通过' },
}

export const ReviewStatusTag = ({ status }: { status?: string }) => {
  const config = reviewStatusConfig[status as ReviewStatus]
  return <Tag color={config?.color || 'default'}>{config?.text || status || '-'}</Tag>
}

export interface ReviewableContent {
  id: string
  subject_id: string
  primary_chapter_id?: string
  source_section_path?: string
  review_status: ReviewStatus
  review_notes?: string
  reviewed_by?: string
  reviewed_at?: string
}

interface ReviewDetail {
  key: string
  label: string
  content: React.ReactNode
}

interface ContentReviewDrawerProps {
  open: boolean
  title: string
  item: ReviewableContent | null
  details: ReviewDetail[]
  submitting?: boolean
  onClose: () => void
  onSubmit: (data: {
    review_status: Exclude<ReviewStatus, 'pending'>
    review_notes?: string
    primary_chapter_id?: string
  }) => void
}

const ContentReviewDrawer = ({
  open,
  title,
  item,
  details,
  submitting = false,
  onClose,
  onSubmit,
}: ContentReviewDrawerProps) => {
  const [reviewNotes, setReviewNotes] = useState('')
  const [primaryChapterId, setPrimaryChapterId] = useState<string>()

  useEffect(() => {
    if (!open || !item) return
    setReviewNotes(item.review_notes || '')
    setPrimaryChapterId(item.primary_chapter_id || undefined)
  }, [item, open])

  const { data: chaptersData, isLoading: isChapterLoading } = useQuery({
    queryKey: ['contentReviewCanonicalChapters', item?.subject_id],
    queryFn: () => getCanonicalChapters(item?.subject_id || ''),
    enabled: open && !!item?.subject_id,
  })

  const chapterOptions = useMemo(
    () =>
      (chaptersData?.data || []).map((chapter) => ({
        label: `${chapter.code ? `${chapter.code} ` : ''}${chapter.name}`,
        value: chapter.id,
      })),
    [chaptersData],
  )

  const submit = (reviewStatus: Exclude<ReviewStatus, 'pending'>) => {
    onSubmit({
      review_status: reviewStatus,
      review_notes: reviewNotes.trim() || undefined,
      primary_chapter_id: primaryChapterId,
    })
  }

  return (
    <Drawer
      title={title}
      open={open}
      onClose={onClose}
      width={620}
      extra={
        <Space>
          <Button danger icon={<CloseOutlined />} loading={submitting} onClick={() => submit('rejected')}>
            未通过
          </Button>
          <Button type="primary" icon={<CheckOutlined />} loading={submitting} onClick={() => submit('approved')}>
            通过
          </Button>
        </Space>
      }
    >
      {item && (
        <>
          <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
            {details.map((detail) => (
              <Descriptions.Item key={detail.key} label={detail.label}>
                {detail.content}
              </Descriptions.Item>
            ))}
            <Descriptions.Item label="识别章节">{item.source_section_path || '-'}</Descriptions.Item>
            <Descriptions.Item label="映射考点">
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="选择大纲考点"
                loading={isChapterLoading}
                value={primaryChapterId}
                onChange={setPrimaryChapterId}
                options={chapterOptions}
                style={{ width: '100%' }}
              />
            </Descriptions.Item>
            <Descriptions.Item label="人工核验">
              <ReviewStatusTag status={item.review_status} />
            </Descriptions.Item>
            <Descriptions.Item label="最近核验">
              {item.reviewed_at
                ? `${new Date(item.reviewed_at).toLocaleString('zh-CN')}${item.reviewed_by ? ` · ${item.reviewed_by}` : ''}`
                : '-'}
            </Descriptions.Item>
          </Descriptions>
          <div style={{ marginBottom: 8, fontWeight: 600 }}>审核备注</div>
          <TextArea
            rows={4}
            value={reviewNotes}
            onChange={(event) => setReviewNotes(event.target.value)}
            placeholder="记录判断依据、需修正内容或其他人工核验信息"
          />
        </>
      )}
    </Drawer>
  )
}

export default ContentReviewDrawer
