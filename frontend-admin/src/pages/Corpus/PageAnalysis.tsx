import { useState } from 'react'
import { Card, Select, Spin, Empty, Row, Col, Collapse, Tag, Divider, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { getDocumentPageAnalysis } from '@/api'

const { Panel } = Collapse
const { Title, Text } = Typography

interface PageAnalysisProps {
  documentId: string
  totalPages: number
}

const PageAnalysis = ({ documentId, totalPages }: PageAnalysisProps) => {
  const [currentPage, setCurrentPage] = useState(1)

  const { data, isLoading } = useQuery({
    queryKey: ['pageAnalysis', documentId, currentPage],
    queryFn: () => getDocumentPageAnalysis(documentId, currentPage),
    enabled: !!documentId && currentPage > 0,
  })

  const pageData = data?.data

  const pageOptions = Array.from({ length: totalPages }, (_, i) => ({
    label: `第 ${i + 1} 页`,
    value: i + 1,
  }))

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Text strong>选择页码：</Text>
        <Select
          value={currentPage}
          onChange={setCurrentPage}
          options={pageOptions}
          style={{ width: 200, marginLeft: 8 }}
        />
      </div>

      {isLoading && (
        <div style={{ textAlign: 'center', padding: 100 }}>
          <Spin size="large" tip="加载页面数据..." />
        </div>
      )}

      {!isLoading && !pageData && <Empty description="无数据" />}

      {!isLoading && pageData && (
        <Row gutter={16}>
          {/* 左侧：原始PDF页 */}
          <Col span={8}>
            <Card title="原始PDF" size="small">
              {pageData.page_image ? (
                <img
                  src={pageData.page_image}
                  alt={`Page ${currentPage}`}
                  style={{ width: '100%', border: '1px solid #d9d9d9' }}
                />
              ) : (
                <Empty description="无法渲染PDF页" />
              )}
              {pageData.page_info && (
                <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
                  尺寸: {pageData.page_info.width} × {pageData.page_info.height}
                </div>
              )}
            </Card>
          </Col>

          {/* 中间：解析结果（原始输出） */}
          <Col span={8}>
            <Card title="解析器输出" size="small">
              {pageData.parser_name && (
                <div style={{ marginBottom: 8 }}>
                  <Tag color="blue">{pageData.parser_name}</Tag>
                </div>
              )}
              <Collapse accordion>
                <Panel header="原始解析数据 (JSON)" key="raw">
                  <pre style={{ maxHeight: 600, overflow: 'auto', fontSize: 11 }}>
                    {JSON.stringify(pageData.raw_parse_data, null, 2)}
                  </pre>
                </Panel>
              </Collapse>
            </Card>
          </Col>

          {/* 右侧：落库数据（blocks + assets） */}
          <Col span={8}>
            <Card title="落库数据" size="small">
              <Title level={5}>Blocks ({pageData.blocks?.length || 0})</Title>
              <Collapse accordion>
                {pageData.blocks?.map((block: any, idx: number) => (
                  <Panel
                    header={
                      <span>
                        <Tag color="blue">{block.block_type}</Tag>
                        {block.content_text?.substring(0, 30)}...
                      </span>
                    }
                    key={idx}
                  >
                    <div>
                      <Text strong>类型:</Text> {block.block_type}<br />
                      <Text strong>顺序:</Text> {block.order_no}<br />
                      <Text strong>内容:</Text>
                      <pre style={{ fontSize: 11, maxHeight: 200, overflow: 'auto' }}>
                        {block.content_text || block.content_md}
                      </pre>
                      {block.bbox && (
                        <>
                          <Text strong>位置:</Text>
                          <pre style={{ fontSize: 10 }}>{JSON.stringify(block.bbox)}</pre>
                        </>
                      )}
                    </div>
                  </Panel>
                ))}
              </Collapse>

              <Divider />

              <Title level={5}>Assets ({pageData.assets?.length || 0})</Title>
              {pageData.assets?.map((asset: any, idx: number) => (
                <Card key={idx} size="small" style={{ marginBottom: 8 }}>
                  <Tag color="green">{asset.asset_type}</Tag>
                  {asset.caption_text && <Text>{asset.caption_text}</Text>}
                  <div
                    style={{
                      fontSize: 11,
                      color: '#666',
                      marginTop: 4,
                      wordBreak: 'break-all',
                    }}
                  >
                    {asset.file_path ? `路径: ${asset.file_path}` : '无独立图片文件（由块提升）'}
                  </div>
                </Card>
              ))}
            </Card>
          </Col>
        </Row>
      )}
    </div>
  )
}

export default PageAnalysis
