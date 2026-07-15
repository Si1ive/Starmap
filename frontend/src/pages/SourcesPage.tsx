import {
  AlertTriangle,
  ArrowRight,
  FileText,
  Filter,
  FolderOpen,
  MoreHorizontal,
  RefreshCw,
  Search,
  Upload,
} from 'lucide-react'
import { sourceFiles } from '../data/fixtures'
import { Button, PageHeading, ProgressBar, SectionHeading, StatusMark } from '../components/Primitives'

const sourceStatus = {
  ready: { tone: 'success', label: '可用' },
  processing: { tone: 'running', label: '解析中' },
  partial: { tone: 'warning', label: '部分可用' },
} as const

export default function SourcesPage() {
  return (
    <div className="page page--wide sources-page">
      <PageHeading
        actions={<Button icon={<Upload size={17} />}>添加资料</Button>}
        description="查看平台知识、个人资料及其可检索状态。解析失败会保留已可用页面。"
        eyebrow="资料"
        title="Agent 当前可以使用的学习材料"
      />

      <div className="source-toolbar">
        <label>
          <Search size={17} />
          <input aria-label="搜索资料" placeholder="搜索文件名或最近引用" />
        </label>
        <button type="button"><Filter size={16} /> 全部来源</button>
      </div>

      <section className="source-table">
        <SectionHeading meta="4 份资料 · 3 份可参与检索" title="资料列表" />
        <div className="source-table__header">
          <span>资料</span>
          <span>可用状态</span>
          <span>最近活动</span>
          <span />
        </div>
        {sourceFiles.map((file) => {
          const status = sourceStatus[file.status as keyof typeof sourceStatus]
          return (
            <div className="source-row" key={file.name}>
              <span className="source-row__icon"><FileText size={20} /></span>
              <span className="source-row__name">
                <strong>{file.name}</strong>
                <small>{file.meta}</small>
              </span>
              <span className="source-row__status">
                <StatusMark tone={status.tone}>{status.label}</StatusMark>
                {file.status === 'processing' ? <ProgressBar value={64} /> : null}
              </span>
              <span className="source-row__detail">{file.detail}</span>
              <button aria-label={`${file.name}更多操作`} title="更多操作" type="button"><MoreHorizontal size={18} /></button>
            </div>
          )
        })}
      </section>

      <section className="source-issues">
        <SectionHeading meta="问题不会让已完成解析的页面失效" title="需要处理" />
        <div className="source-issue">
          <span><AlertTriangle size={19} /></span>
          <div>
            <strong>网络层补充讲义.pdf · 2 页图片识别失败</strong>
            <p>其余 14 页仍可参与检索。失败页为第 7、12 页，可单独重新解析。</p>
          </div>
          <Button icon={<RefreshCw size={16} />} tone="secondary">重试失败页</Button>
        </div>
      </section>

      <section className="source-boundary">
        <span><FolderOpen size={20} /></span>
        <div>
          <strong>当前版本通过网页上传资料</strong>
          <p>Agent 只读取你明确加入的文件。不会扫描本地文件夹，也不会在未确认时修改原文件。</p>
        </div>
        <button type="button">
          查看资料使用规则
          <ArrowRight size={16} />
        </button>
      </section>
    </div>
  )
}
