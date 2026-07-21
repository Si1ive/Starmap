import { useMemo, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import {
  Check,
  Database,
  FileText,
  Filter,
  FolderOpen,
  MoreHorizontal,
  Search,
  Upload,
  X,
} from 'lucide-react'
import { sourceFiles } from '../data/fixtures'
import { Button, IconButton, PageHeading, SectionHeading, SourceBadge } from '../components/Primitives'

type SourceOrigin = 'platform' | 'personal'

interface VisibleSource {
  id: string
  name: string
  meta: string
  detail: string
  origin: SourceOrigin
}

const PERSONAL_SOURCES_KEY = 'starmap-personal-sources'

function readPersonalSources(): VisibleSource[] {
  try {
    const value = window.localStorage.getItem(PERSONAL_SOURCES_KEY)
    if (!value) return []
    const parsed = JSON.parse(value) as VisibleSource[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function SourcesPage() {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<'all' | SourceOrigin>('all')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [personalSources, setPersonalSources] = useState<VisibleSource[]>(readPersonalSources)

  const availableSources = useMemo<VisibleSource[]>(() => {
    const builtInSources = sourceFiles
      .filter((file) => file.status === 'ready')
      .map((file, index) => ({
        id: `built-in-${index}`,
        name: file.name,
        meta: file.meta,
        detail: file.detail,
        origin: file.meta.startsWith('平台') ? 'platform' as const : 'personal' as const,
      }))

    return [...personalSources, ...builtInSources]
  }, [personalSources])

  const filteredSources = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return availableSources.filter((source) => {
      const matchesScope = scope === 'all' || source.origin === scope
      const matchesQuery =
        !keyword ||
        source.name.toLowerCase().includes(keyword) ||
        source.meta.toLowerCase().includes(keyword)
      return matchesScope && matchesQuery
    })
  }, [availableSources, query, scope])

  const setFiles = (files: FileList | File[]) => {
    const nextFiles = Array.from(files).filter((file) =>
      /\.(pdf|md|txt|doc|docx)$/i.test(file.name),
    )
    setSelectedFiles(nextFiles)
  }

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.target.files) setFiles(event.target.files)
  }

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault()
    setFiles(event.dataTransfer.files)
  }

  const addToCorpus = () => {
    if (!selectedFiles.length) return
    const createdAt = Date.now()
    const additions = selectedFiles.map((file, index) => ({
      id: `personal-${createdAt}-${index}`,
      name: file.name,
      meta: `个人资料 · ${formatFileSize(file.size)}`,
      detail: '刚刚加入 · 可供 Agent 检索',
      origin: 'personal' as const,
    }))
    const nextSources = [...additions, ...personalSources]
    setPersonalSources(nextSources)
    window.localStorage.setItem(PERSONAL_SOURCES_KEY, JSON.stringify(nextSources))
    setSelectedFiles([])
    setUploadOpen(false)
  }

  const closeUpload = () => {
    setSelectedFiles([])
    setUploadOpen(false)
  }

  return (
    <div className="page page--wide sources-page">
      <PageHeading
        actions={
          <Button icon={<Upload size={17} />} onClick={() => setUploadOpen(true)}>
            添加资料
          </Button>
        }
        description="这里只展示 Agent 当前可以使用的资料。你也可以上传自己的文件，构建个人语料库。"
        eyebrow="资料"
        title="Agent 当前可以使用的学习材料"
      />

      <div className="source-toolbar">
        <label>
          <Search size={17} />
          <input
            aria-label="搜索资料"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索文件名或最近引用"
            value={query}
          />
        </label>
        <label className="source-filter">
          <Filter size={16} />
          <select
            aria-label="筛选资料来源"
            onChange={(event) => setScope(event.target.value as 'all' | SourceOrigin)}
            value={scope}
          >
            <option value="all">全部来源</option>
            <option value="platform">平台资料</option>
            <option value="personal">个人资料</option>
          </select>
        </label>
      </div>

      <section className="source-table">
        <SectionHeading meta={`${filteredSources.length} 份资料`} title="资料列表" />
        <div className="source-table__header">
          <span>资料</span>
          <span>来源</span>
          <span>最近使用</span>
          <span />
        </div>
        {filteredSources.map((source) => (
            <div className="source-row" key={source.id}>
              <span className="source-row__icon"><FileText size={20} /></span>
              <span className="source-row__name">
                <strong>{source.name}</strong>
                <small>{source.meta}</small>
              </span>
              <span className="source-row__origin">
                <SourceBadge type={source.origin === 'personal' ? 'personal' : 'knowledge'}>
                  {source.origin === 'personal' ? '个人资料' : '平台资料'}
                </SourceBadge>
              </span>
              <span className="source-row__detail">{source.detail}</span>
              <button aria-label={`${source.name}更多操作`} title="更多操作" type="button"><MoreHorizontal size={18} /></button>
            </div>
        ))}
        {!filteredSources.length ? (
          <div className="source-empty">
            <Search size={20} />
            <strong>没有找到匹配的资料</strong>
            <span>调整关键词或资料来源后重试。</span>
          </div>
        ) : null}
      </section>

      <section className="source-corpus-builder">
        <span><Database size={21} /></span>
        <div>
          <strong>构建你的个人语料库</strong>
          <p>上传 PDF、Markdown、文本或 Word 资料，Agent 会将它们与平台资料一起用于回答和练习。只会使用你主动加入的文件。</p>
        </div>
        <Button icon={<FolderOpen size={17} />} onClick={() => setUploadOpen(true)} tone="secondary">
          选择文件
        </Button>
      </section>

      {uploadOpen ? (
        <div className="source-upload-backdrop" role="presentation">
          <section aria-labelledby="source-upload-title" aria-modal="true" className="source-upload-dialog" role="dialog">
            <header>
              <div>
                <p className="eyebrow">个人语料库</p>
                <h2 id="source-upload-title">添加自己的学习资料</h2>
              </div>
              <IconButton label="关闭添加资料" onClick={closeUpload}>
                <X size={19} />
              </IconButton>
            </header>

            <label
              className="source-dropzone"
              onDragOver={(event) => event.preventDefault()}
              onDrop={handleDrop}
            >
              <input
                accept=".pdf,.md,.txt,.doc,.docx"
                multiple
                onChange={handleFileChange}
                ref={fileInputRef}
                type="file"
              />
              <span><Upload size={23} /></span>
              <strong>选择文件或拖到这里</strong>
              <small>支持 PDF、Markdown、TXT、DOC、DOCX，可一次选择多个文件。</small>
            </label>

            {selectedFiles.length ? (
              <div className="source-upload-selection">
                <span>{selectedFiles.length} 个文件</span>
                {selectedFiles.map((file) => (
                  <div key={`${file.name}-${file.size}`}>
                    <FileText size={17} />
                    <strong>{file.name}</strong>
                    <small>{formatFileSize(file.size)}</small>
                    <Check size={16} />
                  </div>
                ))}
              </div>
            ) : null}

            <footer>
              <Button onClick={closeUpload} tone="quiet">取消</Button>
              <Button
                disabled={!selectedFiles.length}
                icon={<Database size={17} />}
                onClick={addToCorpus}
              >
                加入个人语料库
              </Button>
            </footer>
          </section>
        </div>
      ) : null}
    </div>
  )
}
