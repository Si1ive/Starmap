import { Card, Empty, Image, Tag, Tabs, Typography } from 'antd'
import { BlockMath, InlineMath } from 'react-katex'
import 'katex/dist/katex.min.css'

const { Text } = Typography

export interface AssetItem {
  link_id?: string
  asset_id: string
  asset_type: 'figure' | 'table' | 'formula' | 'page_crop' | 'other' | string
  page_no?: number
  file_path?: string
  caption_text?: string
  ocr_text?: string
  bbox?: Record<string, unknown>
  metadata?: Record<string, unknown>
  relation?: string
}

interface Props {
  assets: AssetItem[]
  emptyText?: string
}

const typeColor: Record<string, string> = {
  figure: 'blue',
  table: 'cyan',
  formula: 'purple',
  page_crop: 'magenta',
  other: 'default',
}

const EntityAssets = ({ assets, emptyText = '暂无关联资产' }: Props) => {
  if (!assets || assets.length === 0) {
    return <Empty description={emptyText} image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }

  const figures = assets.filter((a) => a.asset_type === 'figure' || a.asset_type === 'page_crop')
  const tables = assets.filter((a) => a.asset_type === 'table')
  const formulas = assets.filter((a) => a.asset_type === 'formula')
  const others = assets.filter((a) => !['figure', 'page_crop', 'table', 'formula'].includes(a.asset_type))

  const items = [
    figures.length > 0 && {
      key: 'figures',
      label: `图片 (${figures.length})`,
      children: (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
          {figures.map((a) => (
            <Card key={a.asset_id} size="small" styles={{ body: { padding: 8 } }}>
              <Image
                src={a.file_path ? `/api/v1/admin/assets/${a.asset_id}/file` : undefined}
                fallback="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNTAiIGhlaWdodD0iMTAwIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjZjVmNWY1Ii8+PHRleHQgeD0iNTAlIiB5PSI1MCUiIGRvbWluYW50LWJhc2VsaW5lPSJtaWRkbGUiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGZpbGw9IiM5OTkiPm5vIGltYWdlPC90ZXh0Pjwvc3ZnPg=="
                alt={a.caption_text || `figure-${a.asset_id}`}
                style={{ width: '100%', objectFit: 'contain' }}
              />
              <div style={{ marginTop: 4 }}>
                <Tag color={typeColor[a.asset_type]}>{a.asset_type}</Tag>
                {a.page_no && <Text type="secondary" style={{ fontSize: 11 }}>p.{a.page_no}</Text>}
              </div>
              {a.caption_text && <Text type="secondary" style={{ fontSize: 11 }} ellipsis>{a.caption_text}</Text>}
            </Card>
          ))}
        </div>
      ),
    },
    tables.length > 0 && {
      key: 'tables',
      label: `表格 (${tables.length})`,
      children: (
        <div>
          {tables.map((a) => {
            const html = (a.metadata as any)?.html as string | undefined
            return (
              <Card key={a.asset_id} size="small" style={{ marginBottom: 12 }}
                title={<><Tag color={typeColor.table}>table</Tag>{a.page_no && <Text type="secondary" style={{ fontSize: 12 }}>p.{a.page_no}</Text>}</>}>
                {html ? (
                  <div className="entity-asset-table" style={{ overflowX: 'auto' }}
                    dangerouslySetInnerHTML={{ __html: html }} />
                ) : (
                  <Text type="secondary">无 HTML，原文：{a.caption_text || '-'}</Text>
                )}
              </Card>
            )
          })}
        </div>
      ),
    },
    formulas.length > 0 && {
      key: 'formulas',
      label: `公式 (${formulas.length})`,
      children: (
        <div>
          {formulas.map((a) => {
            const latex = (a.metadata as any)?.latex as string | undefined
            return (
              <Card key={a.asset_id} size="small" style={{ marginBottom: 12 }}
                title={<><Tag color={typeColor.formula}>formula</Tag>{a.page_no && <Text type="secondary" style={{ fontSize: 12 }}>p.{a.page_no}</Text>}</>}>
                {latex ? (
                  <div style={{ overflow: 'auto' }}>
                    <BlockMath math={latex} />
                    <Text type="secondary" style={{ fontSize: 11, fontFamily: 'monospace' }}>{latex}</Text>
                  </div>
                ) : (
                  <Text type="secondary">{a.caption_text || '无 LaTeX 内容'}</Text>
                )}
              </Card>
            )
          })}
        </div>
      ),
    },
    others.length > 0 && {
      key: 'others',
      label: `其他 (${others.length})`,
      children: (
        <div>
          {others.map((a) => (
            <Card key={a.asset_id} size="small" style={{ marginBottom: 8 }}>
              <Tag color={typeColor.other}>{a.asset_type}</Tag>
              <Text>{a.caption_text || a.ocr_text || '-'}</Text>
            </Card>
          ))}
        </div>
      ),
    },
  ].filter(Boolean) as any[]

  return <Tabs items={items} />
}

export default EntityAssets

// Inline 公式辅助组件，知识点 / 题目正文里若混了 $...$ 可单独使用
export const InlineLatex = ({ math }: { math: string }) => <InlineMath math={math} />
