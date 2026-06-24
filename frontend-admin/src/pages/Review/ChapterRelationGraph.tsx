import { useState, useCallback } from 'react'
import { Card, Select, Space, Spin, Typography, Tag, Empty, Button, InputNumber, Form } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, TitleComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useQuery } from '@tanstack/react-query'
import { listChapterRelations } from '@/api/chapter-relation'
import { listOutlines, getOutlineChapters } from '@/api/outline'
import type { OutlineSummary, OutlineChapter } from '@/api/outline'

echarts.use([GraphChart, TooltipComponent, TitleComponent, CanvasRenderer])

const { Text } = Typography

const relationColorMap: Record<string, string> = {
  similar_to: '#36CFC9',
  prerequisite: '#597EF7',
  contrast_with: '#FF7A45',
  common_confusion: '#EB2F96',
}

const relationLabelMap: Record<string, string> = {
  similar_to: '相似',
  prerequisite: '前置',
  contrast_with: '对比',
  common_confusion: '易混淆',
}

interface GraphNode {
  id: string
  name: string
  category: 'chapter' | 'knowledge_point'
  symbolSize: number
  itemStyle?: { color: string }
  tooltip?: { formatter: string }
}

interface GraphLink {
  source: string
  target: string
  label?: { show: boolean; formatter: string }
  lineStyle?: { color: string; width: number; curveness: number }
}

const ChapterRelationGraphPage = () => {
  const [selectedOutlineId, setSelectedOutlineId] = useState<string>()
  const [selectedSubjectId, setSelectedSubjectId] = useState<string>()
  const [maxRelations, setMaxRelations] = useState(50)

  // 大纲列表
  const { data: outlinesData } = useQuery({
    queryKey: ['outlines'],
    queryFn: () => listOutlines(),
  })
  const outlines = outlinesData?.data || []

  // 大纲章节树
  const { data: chaptersData } = useQuery({
    queryKey: ['outlineChapters', selectedOutlineId, selectedSubjectId],
    queryFn: () => getOutlineChapters(selectedOutlineId!, selectedSubjectId),
    enabled: !!selectedOutlineId,
  })

  // 考点关系列表
  const { data: relationsData, isLoading } = useQuery({
    queryKey: ['chapterRelationsForGraph', maxRelations],
    queryFn: () => listChapterRelations({
      review_status: 'approved',
      page_size: maxRelations,
      page: 1,
    }),
  })

  const buildGraphOption = useCallback(() => {
    const relations = relationsData?.data?.items || []
    const chapters = chaptersData?.data || []

    const chapterMap = new Map<string, OutlineChapter>()
    const flattenChapters = (list: OutlineChapter[]) => {
      for (const ch of list) {
        chapterMap.set(ch.id, ch)
        if (ch.children) flattenChapters(ch.children)
      }
    }
    flattenChapters(chapters)

    const nodeMap = new Map<string, GraphNode>()
    const links: GraphLink[] = []

    for (const rel of relations) {
      // 源考点节点
      if (!nodeMap.has(rel.source_chapter_id)) {
        const ch = chapterMap.get(rel.source_chapter_id)
        nodeMap.set(rel.source_chapter_id, {
          id: rel.source_chapter_id,
          name: ch?.name || rel.source_chapter_name || rel.source_chapter_id,
          category: 'chapter',
          symbolSize: 40,
          itemStyle: { color: '#1677FF' },
        })
      }
      // 目标考点节点
      if (!nodeMap.has(rel.target_chapter_id)) {
        const ch = chapterMap.get(rel.target_chapter_id)
        nodeMap.set(rel.target_chapter_id, {
          id: rel.target_chapter_id,
          name: ch?.name || rel.target_chapter_name || rel.target_chapter_id,
          category: 'chapter',
          symbolSize: 40,
          itemStyle: { color: '#1677FF' },
        })
      }

      // 边
      const color = relationColorMap[rel.relation_type] || '#8C8C8C'
      links.push({
        source: rel.source_chapter_id,
        target: rel.target_chapter_id,
        label: {
          show: true,
          formatter: relationLabelMap[rel.relation_type] || rel.relation_type,
        },
        lineStyle: {
          color,
          width: Math.max(1, (rel.confidence || 0.5) * 3),
          curveness: 0.2,
        },
      })
    }

    const nodes = Array.from(nodeMap.values())

    return {
      tooltip: {
        formatter: (params: any) => {
          if (params.dataType === 'edge') {
            return `${params.data.source} → ${params.data.target}<br/>${params.data.label?.formatter || ''}`
          }
          return `<strong>${params.name}</strong>`
        },
      },
      legend: {
        data: [
          { name: '考点', icon: 'circle' },
          ...Object.entries(relationLabelMap).map(([, v]) => ({ name: v, icon: 'line' })),
        ],
        bottom: 0,
      },
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          force: {
            repulsion: 300,
            edgeLength: [150, 300],
            gravity: 0.1,
          },
          data: nodes,
          links,
          categories: [
            { name: '考点', itemStyle: { color: '#1677FF' } },
          ],
          label: {
            show: true,
            fontSize: 12,
            formatter: (p: any) => {
              const name = p.name || ''
              return name.length > 10 ? name.slice(0, 10) + '...' : name
            },
          },
          emphasis: {
            focus: 'adjacency',
            lineStyle: { width: 4 },
          },
          lineStyle: {
            opacity: 0.7,
          },
        },
      ],
    }
  }, [relationsData, chaptersData])

  const subjects = chaptersData?.data || []
  const graphOption = buildGraphOption()
  const relationCount = relationsData?.data?.total || 0

  return (
    <div>
      <h3 style={{ marginBottom: 8 }}>考点关联图谱</h3>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        可视化展示已审核通过的跨章节考点关联关系。节点为考点，边为关联类型。可拖拽、缩放。
      </Text>

      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            placeholder="选择大纲"
            style={{ width: 240 }}
            value={selectedOutlineId}
            onChange={(v) => { setSelectedOutlineId(v); setSelectedSubjectId(undefined) }}
            options={outlines.map((o: OutlineSummary) => ({ label: `${o.name} (${o.year})`, value: o.id }))}
          />
          <Select
            placeholder="选择学科（可选）"
            style={{ width: 200 }}
            value={selectedSubjectId}
            onChange={setSelectedSubjectId}
            allowClear
            disabled={!selectedOutlineId}
            options={subjects.map((s: any) => ({ label: s.name, value: s.subject_id || s.id }))}
          />
          <Form.Item label="最大关系数" style={{ marginBottom: 0 }}>
            <InputNumber min={10} max={200} value={maxRelations} onChange={(v) => setMaxRelations(v || 50)} />
          </Form.Item>
          <Button icon={<ReloadOutlined />} onClick={() => {}}>刷新</Button>
        </Space>
      </Card>

      <Card>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
        ) : relationCount === 0 ? (
          <Empty description="暂无已审核的考点关联数据。请先构建考点关系并审核通过。" />
        ) : (
          <>
            <div style={{ marginBottom: 8 }}>
              <Space>
                <Text type="secondary">共 {relationCount} 条已审核关联</Text>
                {Object.entries(relationLabelMap).map(([k, v]) => (
                  <Tag key={k} color={relationColorMap[k]}>{v}</Tag>
                ))}
              </Space>
            </div>
            <ReactEChartsCore
              echarts={echarts}
              option={graphOption}
              style={{ height: 600, width: '100%' }}
              notMerge
            />
          </>
        )}
      </Card>
    </div>
  )
}

export default ChapterRelationGraphPage
