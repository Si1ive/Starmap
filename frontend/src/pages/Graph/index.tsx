import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Button, Typography, message } from 'antd'
import { ArrowLeftOutlined, ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons'
import * as d3 from 'd3'
import { getPersonRelations } from '@/api/person'
import Loading from '@/components/Loading'
import type { IRelationNode, IRelationEdge } from '@/types'

const { Title, Text } = Typography

interface GraphData {
  center: IRelationNode
  nodes: IRelationNode[]
  edges: IRelationEdge[]
}

// D3 内部使用的节点类型（包含 x, y 等模拟属性）
interface D3Node extends IRelationNode {
  x?: number
  y?: number
  fx?: number | null
  fy?: number | null
}

const GraphPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const svgRef = useRef<SVGSVGElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(false)
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 })

  // 监听容器尺寸变化
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const { width, height } = containerRef.current.getBoundingClientRect()
        setDimensions({ width: Math.max(width, 600), height: Math.max(height, 500) })
      }
    }

    updateDimensions()
    window.addEventListener('resize', updateDimensions)
    return () => window.removeEventListener('resize', updateDimensions)
  }, [])

  // 获取关系数据
  const fetchRelations = useCallback(async () => {
    if (!id) return

    setLoading(true)
    try {
      const data = await getPersonRelations(id, { depth: 2 })

      if (data) {
        // 确保中心节点在 nodes 中
        const nodes = data.nodes || []
        const centerExists = nodes.some((n: IRelationNode) => n.id === data.center?.id)

        if (!centerExists && data.center) {
          nodes.unshift(data.center)
        }

        setGraphData({
          center: data.center,
          nodes,
          edges: data.edges || []
        })
      }
    } catch (error) {
      console.error('获取关系数据错误:', error)
      message.error('获取关系数据失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    fetchRelations()
  }, [fetchRelations])

  // D3 力导向图渲染
  useEffect(() => {
    if (!graphData || !svgRef.current) return

    const { width, height } = dimensions
    const svg = d3.select(svgRef.current)

    // 清空 SVG
    svg.selectAll('*').remove()

    // 创建缩放行为
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform)
      })

    svg.call(zoom)

    const g = svg.append('g')

    // 准备数据 - 转换为 D3Node
    const nodes: D3Node[] = graphData.nodes.map((n) => ({ ...n }))
    const links = graphData.edges.map((e) => ({ ...e }))

    // 创建力导向模拟
    const simulation = d3.forceSimulation<D3Node>(nodes)
      .force('link', d3.forceLink<D3Node, typeof links[0]>(links)
        .id((d) => d.id)
        .distance(150)
      )
      .force('charge', d3.forceManyBody().strength(-500))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(40))

    // 创建箭头标记
    svg.append('defs')
      .append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 35)
      .attr('refY', 0)
      .attr('markerWidth', 8)
      .attr('markerHeight', 8)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#999')

    // 绘制连线
    const link = g.append('g')
      .selectAll('line')
      .data(links)
      .enter()
      .append('line')
      .attr('stroke', '#999')
      .attr('stroke-width', 1.5)
      .attr('marker-end', 'url(#arrowhead)')

    // 绘制连线标签
    const linkLabel = g.append('g')
      .selectAll('text')
      .data(links)
      .enter()
      .append('text')
      .attr('font-size', 11)
      .attr('fill', '#666')
      .attr('text-anchor', 'middle')
      .text((d) => d.type)

    // 绘制节点
    const node = g.append('g')
      .selectAll('g')
      .data(nodes)
      .enter()
      .append('g')
      .attr('cursor', 'pointer')
      .call(d3.drag<SVGGElement, D3Node>()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart()
          d.fx = d.x ?? null
          d.fy = d.y ?? null
        })
        .on('drag', (event, d) => {
          d.fx = event.x
          d.fy = event.y
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0)
          d.fx = null
          d.fy = null
        })
      )
      .on('click', (_event, d) => {
        if (d.id !== id) {
          navigate(`/person/${d.id}`)
        }
      })

    // 节点圆形背景
    node.append('circle')
      .attr('r', 30)
      .attr('fill', (d) => (d.id === id ? '#1890ff' : '#52c41a'))
      .attr('stroke', '#fff')
      .attr('stroke-width', 3)
      .attr('opacity', 0.9)

    // 节点文字（名字首字）
    node.append('text')
      .attr('dy', 5)
      .attr('text-anchor', 'middle')
      .attr('font-size', 10)
      .attr('fill', '#fff')
      .text((d) => d.name.charAt(0))

    // 节点名称标签
    node.append('text')
      .attr('dy', 50)
      .attr('text-anchor', 'middle')
      .attr('font-size', 12)
      .attr('font-weight', 500)
      .attr('fill', '#333')
      .text((d) => d.name)

    // 更新位置
    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as unknown as D3Node).x!)
        .attr('y1', (d) => (d.source as unknown as D3Node).y!)
        .attr('x2', (d) => (d.target as unknown as D3Node).x!)
        .attr('y2', (d) => (d.target as unknown as D3Node).y!)

      linkLabel
        .attr('x', (d) => ((d.source as unknown as D3Node).x! + (d.target as unknown as D3Node).x!) / 2)
        .attr('y', (d) => ((d.source as unknown as D3Node).y! + (d.target as unknown as D3Node).y!) / 2)

      node.attr('transform', (d) => `translate(${d.x},${d.y})`)
    })

    return () => {
      simulation.stop()
    }
  }, [graphData, dimensions, id, navigate])

  const handleBack = useCallback(() => {
    navigate(-1)
  }, [navigate])

  const handleZoomIn = useCallback(() => {
    if (svgRef.current) {
      const svg = d3.select(svgRef.current)
      const currentTransform = d3.zoomTransform(svgRef.current)
      const zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      svg.transition().duration(300).call(
        zoomBehavior.transform as any,
        currentTransform.scale(1.3)
      )
    }
  }, [])

  const handleZoomOut = useCallback(() => {
    if (svgRef.current) {
      const svg = d3.select(svgRef.current)
      const currentTransform = d3.zoomTransform(svgRef.current)
      const zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      svg.transition().duration(300).call(
        zoomBehavior.transform as any,
        currentTransform.scale(0.7)
      )
    }
  }, [])

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Button icon={<ArrowLeftOutlined />} onClick={handleBack}>
          返回
        </Button>
        <div>
          <Button icon={<ZoomInOutlined />} onClick={handleZoomIn} style={{ marginRight: 8 }}>
            放大
          </Button>
          <Button icon={<ZoomOutOutlined />} onClick={handleZoomOut}>
            缩小
          </Button>
        </div>
      </div>

      <Card
        title={
          <div>
            <Title level={4} style={{ margin: 0 }}>
              关系图谱
            </Title>
            {graphData?.center && (
              <Text type="secondary">
                中心: {graphData.center.name}
              </Text>
            )}
          </div>
        }
      >
        <Loading loading={loading} empty={!graphData && !loading}>
          <div
            ref={containerRef}
            style={{
              width: '100%',
              height: 600,
              background: '#fafafa',
              borderRadius: 8,
              overflow: 'hidden'
            }}
          >
            <svg
              ref={svgRef}
              width={dimensions.width}
              height={dimensions.height}
              style={{ display: 'block' }}
            />
          </div>
        </Loading>
      </Card>
    </div>
  )
}

export default GraphPage
