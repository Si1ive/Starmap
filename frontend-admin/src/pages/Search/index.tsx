import { useState } from 'react'
import { Card, Input, Button, Select, Space, Tag, Table, Tabs, message, Empty, Spin, List } from 'antd'
import { SearchOutlined, BranchesOutlined, BuildOutlined } from '@ant-design/icons'
import { useQuery, useMutation } from '@tanstack/react-query'
import { searchDebug, searchWithRelations, buildSegments, getSubjects, getChapters } from '@/api'
import type { SearchResult, SearchDebugResult } from '@/types'

const { Search } = Input

const segmentTypeConfig: Record<string, { color: string; text: string }> = {
  title: { color: 'blue', text: '标题' }, content: { color: 'green', text: '内容' },
  explanation: { color: 'purple', text: '解析' }, option: { color: 'cyan', text: '选项' },
}

const SearchDebugPage = () => {
  const [query, setQuery] = useState('')
  const [subjectId, setSubjectId] = useState('')
  const [chapterIds, setChapterIds] = useState<string[]>([])
  const [entityType, setEntityType] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [limit, setLimit] = useState(10)
  const [activeTab, setActiveTab] = useState('search')
  const [results, setResults] = useState<SearchResult[]>([])
  const [relationResults, setRelationResults] = useState<SearchDebugResult | null>(null)

  const { data: subjectsData } = useQuery({ queryKey: ['subjects'], queryFn: getSubjects })
  const { data: chaptersData } = useQuery({
    queryKey: ['chapters', subjectId], queryFn: () => getChapters(subjectId), enabled: !!subjectId,
  })

  const subjects = subjectsData?.data || []
  const chapters = chaptersData?.data || []

  const searchMut = useMutation({
    mutationFn: async () => {
      if (!query.trim()) throw new Error('请输入查询内容')
      if (activeTab === 'search') {
        return searchDebug({ query, subject_id: subjectId || undefined, chapter_ids: chapterIds.length > 0 ? chapterIds : undefined, entity_type: entityType || undefined, mode, limit })
      } else {
        return searchWithRelations({ query, subject_id: subjectId || undefined, chapter_ids: chapterIds.length > 0 ? chapterIds : undefined, limit })
      }
    },
    onSuccess: (res) => {
      if (activeTab === 'search') {
        setResults((res.data as any)?.results || [])
      } else {
        setRelationResults(res.data as any)
      }
    },
  })

  const buildMut = useMutation({
    mutationFn: () => buildSegments({ subject_id: subjectId || undefined }),
    onSuccess: () => message.success('构建完成'),
  })

  const resultColumns = [
    { title: '类型', dataIndex: 'entity_type', key: 'entity_type', width: 100, render: (t: string) => (
      <Tag color={t === 'knowledge_point' ? 'blue' : 'green'}>{t === 'knowledge_point' ? '知识点' : '题目'}</Tag>
    )},
    { title: '段落类型', dataIndex: 'segment_type', key: 'segment_type', width: 100, render: (t: string) => {
      const cfg = segmentTypeConfig[t] || { color: 'default', text: t }
      return <Tag color={cfg.color}>{cfg.text}</Tag>
    }},
    { title: '内容', dataIndex: 'content_text', key: 'content_text', ellipsis: true, render: (t: string) => t?.slice(0, 150) || '-' },
    { title: '分数', dataIndex: 'score', key: 'score', width: 80, sorter: (a: SearchResult, b: SearchResult) => a.score - b.score, render: (v: number) => v?.toFixed(4) || '-' },
    { title: '来源', key: 'source', width: 180, render: (_: any, record: SearchResult) => {
      const src = record.source
      if (!src?.filename) return '-'
      return <span style={{ fontSize: 12, color: '#999' }}>{src.filename}{src.page_no ? ` p.${src.page_no}` : ''}</span>
    }},
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0 }}><SearchOutlined style={{ marginRight: 8 }} />检索调试</h3>
        <Button icon={<BuildOutlined />} loading={buildMut.isPending} onClick={() => buildMut.mutate()}>构建 Segments</Button>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Search
          placeholder="输入检索内容，如：什么是二叉树的遍历"
          value={query} onChange={(e) => setQuery(e.target.value)}
          onSearch={() => searchMut.mutate()}
          enterButton={<><SearchOutlined /> 检索</>}
          size="large" loading={searchMut.isPending}
          style={{ marginBottom: 16 }}
        />
        <Space wrap>
          <Select value={subjectId || 'all'} style={{ width: 150 }}
            onChange={(v) => { setSubjectId(v === 'all' ? '' : v); setChapterIds([]) }}
            options={[{ label: '全部学科', value: 'all' }, ...subjects.map((s: any) => ({ label: s.name, value: s.id }))]}
          />
          <Select mode="multiple" value={chapterIds} style={{ width: 200 }} onChange={setChapterIds}
            placeholder="选择章节" options={chapters.map((c: any) => ({ label: c.name, value: c.id }))} maxTagCount={2}
          />
          <Select value={entityType || 'all'} style={{ width: 120 }}
            onChange={(v) => setEntityType(v === 'all' ? '' : v)}
            options={[{ label: '全部类型', value: 'all' }, { label: '知识点', value: 'knowledge_point' }, { label: '题目', value: 'question' }]}
          />
          <Select value={mode} style={{ width: 140 }} onChange={setMode}
            options={[{ label: 'Hybrid 混合', value: 'hybrid' }, { label: 'Dense 向量', value: 'dense' }, { label: 'Sparse 关键词', value: 'sparse' }]}
          />
          <Select value={limit} style={{ width: 100 }} onChange={setLimit}
            options={[{ label: 'Top 5', value: 5 }, { label: 'Top 10', value: 10 }, { label: 'Top 20', value: 20 }]}
          />
        </Space>
      </Card>

      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'search', label: '基础检索',
            children: searchMut.isPending ? <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div> :
              results.length > 0 ? <Table dataSource={results} columns={resultColumns} rowKey="segment_id" pagination={false} size="small" /> :
                <Empty description="输入查询后点击检索" />,
          },
          {
            key: 'relations', label: '关系扩展检索',
            children: searchMut.isPending ? <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div> :
              relationResults ? (
                <div>
                  <h4>主检索结果（{relationResults.primary_results?.length || 0}）</h4>
                  <Table dataSource={relationResults.primary_results} columns={resultColumns} rowKey="segment_id" pagination={false} size="small" style={{ marginBottom: 24 }} />
                  {relationResults.relations?.length > 0 && (
                    <>
                      <h4><BranchesOutlined style={{ marginRight: 8 }} />关系边（{relationResults.relations.length}）</h4>
                      <List dataSource={relationResults.relations} size="small" style={{ marginBottom: 24 }}
                        renderItem={(rel: any) => (
                          <List.Item>
                            <Space><Tag color="blue">{rel.relation_type}</Tag><span>{rel.related_knowledge_title}</span>
                              {rel.evidence_text && <span style={{ color: '#999' }}>({rel.evidence_text.slice(0, 50)})</span>}
                            </Space>
                          </List.Item>
                        )}
                      />
                    </>
                  )}
                  {relationResults.related_results?.length > 0 && (
                    <>
                      <h4>关联知识点（{relationResults.related_results.length}）</h4>
                      <Table dataSource={relationResults.related_results} columns={resultColumns} rowKey="segment_id" pagination={false} size="small" />
                    </>
                  )}
                </div>
              ) : <Empty description="输入查询后点击检索" />,
          },
        ]} />
      </Card>
    </div>
  )
}

export default SearchDebugPage
