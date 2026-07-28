import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import {
  AlertCircle,
  BookOpen,
  Check,
  Database,
  FileText,
  Filter,
  FolderOpen,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  deleteLibrarySource,
  listLibrarySources,
  setLibrarySourceRetrieval,
  uploadLibrarySources,
} from "../api/library";
import type { LibrarySource } from "../api/library";
import {
  Button,
  IconButton,
  PageHeading,
  SectionHeading,
  SourceBadge,
} from "../components/Primitives";

type SourceOrigin = "platform" | "personal";

const statusCopy: Record<LibrarySource["status"], string> = {
  pending: "等待入库",
  parsing: "正在解析",
  parsed: "解析完成",
  extracting: "正在建立索引",
  indexed: "可检索",
  failed: "入库失败",
  archived: "已归档",
};

function formatFileSize(bytes: number | null) {
  if (!bytes) return "大小未知";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function SourcesPage() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"all" | SourceOrigin>("all");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [sources, setSources] = useState<LibrarySource[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [mutatingId, setMutatingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readerSource, setReaderSource] = useState<LibrarySource | null>(null);

  const loadSources = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      setSources(await listLibrarySources());
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "资料列表加载失败",
      );
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);
  useEffect(() => {
    const hasActiveIngestion = sources.some((source) =>
      ["pending", "parsing", "parsed", "extracting"].includes(source.status),
    );
    if (!hasActiveIngestion) return;
    const timer = window.setInterval(() => void loadSources(true), 4000);
    return () => window.clearInterval(timer);
  }, [loadSources, sources]);

  const filteredSources = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return sources.filter((source) => {
      const matchesScope = scope === "all" || source.origin === scope;
      return (
        matchesScope &&
        (!keyword || source.name.toLowerCase().includes(keyword))
      );
    });
  }, [query, scope, sources]);

  const setFiles = (files: FileList | File[]) => {
    setSelectedFiles(
      Array.from(files).filter((file) => /\.pdf$/i.test(file.name)),
    );
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.target.files) setFiles(event.target.files);
  };

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setFiles(event.dataTransfer.files);
  };

  const addToCorpus = async () => {
    if (!selectedFiles.length || uploading) return;
    setUploading(true);
    setError(null);
    try {
      await uploadLibrarySources(selectedFiles);
      setSelectedFiles([]);
      setUploadOpen(false);
      await loadSources();
    } catch (uploadError) {
      setError(
        uploadError instanceof Error ? uploadError.message : "资料入库失败",
      );
    } finally {
      setUploading(false);
    }
  };

  const closeUpload = () => {
    if (uploading) return;
    setSelectedFiles([]);
    setUploadOpen(false);
  };

  const toggleRetrieval = async (source: LibrarySource) => {
    if (mutatingId) return;
    setMutatingId(source.id);
    try {
      await setLibrarySourceRetrieval(source.id, !source.retrieval_enabled);
      await loadSources(true);
    } catch (mutationError) {
      setError(
        mutationError instanceof Error ? mutationError.message : "资料授权修改失败",
      );
    } finally {
      setMutatingId(null);
    }
  };

  const removeSource = async (source: LibrarySource) => {
    if (mutatingId || !window.confirm(`确认删除“${source.name}”？删除后会立即退出 Agent 检索。`)) return;
    setMutatingId(source.id);
    try {
      await deleteLibrarySource(source.id);
      if (readerSource?.id === source.id) setReaderSource(null);
      await loadSources(true);
    } catch (mutationError) {
      setError(
        mutationError instanceof Error ? mutationError.message : "资料删除失败",
      );
    } finally {
      setMutatingId(null);
    }
  };

  return (
    <div className="page page--wide sources-page">
      <PageHeading
        actions={
          <Button
            icon={<Upload size={17} />}
            onClick={() => setUploadOpen(true)}
          >
            添加资料
          </Button>
        }
        description="只展示已经进入平台语料库的资料。个人资料仅属于当前账号，并只参与当前账号的检索。"
        eyebrow="资料"
        title="你的真实学习资料库"
      />

      <div className="source-toolbar">
        <label>
          <Search size={17} />
          <input
            aria-label="搜索资料"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索已入库资料"
            value={query}
          />
        </label>
        <label className="source-filter">
          <Filter size={16} />
          <select
            aria-label="筛选资料来源"
            onChange={(event) =>
              setScope(event.target.value as "all" | SourceOrigin)
            }
            value={scope}
          >
            <option value="all">全部来源</option>
            <option value="platform">平台资料</option>
            <option value="personal">个人资料</option>
          </select>
        </label>
        <IconButton label="刷新资料状态" onClick={() => void loadSources()}>
          <RefreshCw className={loading ? "spin" : ""} size={17} />
        </IconButton>
      </div>

      {error ? (
        <div className="source-notice source-notice--error">
          <AlertCircle size={17} />
          <span>{error}</span>
        </div>
      ) : null}

      <section className="source-table">
        <SectionHeading
          meta={loading ? "正在读取数据库" : `${filteredSources.length} 份资料`}
          title="资料列表"
        />
        <div className="source-table__header">
          <span>资料</span>
          <span>来源</span>
          <span>入库状态</span>
          <span>操作</span>
        </div>
        {!loading &&
          filteredSources.map((source) => (
            <div
              className={`source-row source-row--${source.status}`}
              key={source.id}
            >
              <span className="source-row__icon">
                <FileText size={20} />
              </span>
              <span className="source-row__name">
                <strong>{source.name}</strong>
                <small>
                  {formatFileSize(source.file_size)}
                  {source.page_count ? ` · ${source.page_count} 页` : ""}
                </small>
              </span>
              <span className="source-row__origin">
                <SourceBadge
                  type={source.origin === "personal" ? "personal" : "knowledge"}
                >
                  {source.origin === "personal" ? "仅当前账号" : "平台资料"}
                </SourceBadge>
              </span>
              <span className="source-row__detail">
                <i
                  className={`source-status source-status--${source.status}`}
                />
                {source.error_detail || statusCopy[source.status]}
                {source.origin === "personal" && !source.retrieval_enabled
                  ? " · 已暂停 Agent 使用"
                  : ""}
              </span>
              <span className="source-row__actions">
                <IconButton
                  disabled={!source.read_url}
                  label={source.read_url ? `阅读 ${source.name}` : "原始 PDF 尚未完成入库"}
                  onClick={() => setReaderSource(source)}
                >
                  {source.read_url ? (
                    <BookOpen size={18} />
                  ) : (
                    <Loader2
                      className={
                        ["pending", "parsing", "parsed", "extracting"].includes(
                          source.status,
                        )
                          ? "spin"
                          : ""
                      }
                      size={17}
                    />
                  )}
                </IconButton>
                {source.origin === "personal" ? (
                  <>
                    <IconButton
                      disabled={mutatingId === source.id}
                      label={source.retrieval_enabled ? "暂停 Agent 使用" : "允许 Agent 使用"}
                      onClick={() => void toggleRetrieval(source)}
                    >
                      {mutatingId === source.id ? (
                        <Loader2 className="spin" size={17} />
                      ) : source.retrieval_enabled ? (
                        <Pause size={17} />
                      ) : (
                        <Play size={17} />
                      )}
                    </IconButton>
                    <IconButton
                      disabled={mutatingId === source.id}
                      label={`删除 ${source.name}`}
                      onClick={() => void removeSource(source)}
                    >
                      <Trash2 size={17} />
                    </IconButton>
                  </>
                ) : null}
              </span>
            </div>
          ))}
        {!loading && !filteredSources.length ? (
          <div className="source-empty">
            <Search size={20} />
            <strong>没有已入库的匹配资料</strong>
            <span>添加 PDF 后，解析和索引状态会在这里实时更新。</span>
          </div>
        ) : null}
      </section>

      <section className="source-corpus-builder">
        <span>
          <Database size={21} />
        </span>
        <div>
          <strong>个人资料按账号隔离</strong>
          <p>
            上传会发起真实解析、题目与知识点抽取和向量索引。只有当前用户能阅读和检索这些内容。
          </p>
        </div>
        <Button
          icon={<FolderOpen size={17} />}
          onClick={() => setUploadOpen(true)}
          tone="secondary"
        >
          选择 PDF
        </Button>
      </section>

      {uploadOpen ? (
        <div className="source-upload-backdrop" role="presentation">
          <section
            aria-labelledby="source-upload-title"
            aria-modal="true"
            className="source-upload-dialog"
            role="dialog"
          >
            <header>
              <div>
                <p className="eyebrow">个人资料入库</p>
                <h2 id="source-upload-title">添加原始 PDF</h2>
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
                accept=".pdf,application/pdf"
                multiple
                onChange={handleFileChange}
                ref={fileInputRef}
                type="file"
              />
              <span>
                <Upload size={23} />
              </span>
              <strong>选择 PDF 或拖到这里</strong>
              <small>文件会真实上传并进入解析、抽取和索引流程。</small>
            </label>
            {selectedFiles.length ? (
              <div className="source-upload-selection">
                <span>{selectedFiles.length} 个 PDF</span>
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
              <Button disabled={uploading} onClick={closeUpload} tone="quiet">
                取消
              </Button>
              <Button
                disabled={!selectedFiles.length || uploading}
                icon={
                  uploading ? (
                    <Loader2 className="spin" size={17} />
                  ) : (
                    <Database size={17} />
                  )
                }
                onClick={() => void addToCorpus()}
              >
                {uploading ? "正在提交" : "发起入库"}
              </Button>
            </footer>
          </section>
        </div>
      ) : null}

      {readerSource?.read_url ? (
        <div
          className="pdf-reader"
          role="dialog"
          aria-label={`${readerSource.name} PDF 阅读器`}
          aria-modal="true"
        >
          <header>
            <div>
              <span className="eyebrow">原始入库文件</span>
              <strong>{readerSource.name}</strong>
              <small>
                {readerSource.page_count
                  ? `${readerSource.page_count} 页`
                  : "PDF"}
              </small>
            </div>
            <IconButton
              label="关闭 PDF 阅读器"
              onClick={() => setReaderSource(null)}
            >
              <X size={20} />
            </IconButton>
          </header>
          <iframe src={readerSource.read_url} title={readerSource.name} />
        </div>
      ) : null}
    </div>
  );
}
