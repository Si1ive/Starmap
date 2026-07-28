import { fetchCurrentSession } from "../auth";

const LIBRARY_BASE = "/api/v1/app/library";

interface ApiEnvelope<T> {
  data?: T;
  detail?: string;
  message?: string;
}

export type LibrarySourceStatus =
  | "pending"
  | "parsing"
  | "parsed"
  | "extracting"
  | "indexed"
  | "failed"
  | "archived";

export interface LibrarySource {
  id: string;
  name: string;
  origin: "platform" | "personal";
  status: LibrarySourceStatus;
  retrieval_enabled: boolean;
  error_detail: string | null;
  file_size: number | null;
  file_type: string;
  doc_type: string;
  document_id: string | null;
  page_count: number | null;
  created_at: string;
  updated_at: string;
  read_url: string | null;
}

export async function listLibrarySources(): Promise<LibrarySource[]> {
  const response = await fetch(`${LIBRARY_BASE}/sources?page_size=100`, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  const payload = (await response.json().catch(() => ({}))) as ApiEnvelope<{
    items: LibrarySource[];
  }>;
  if (!response.ok || !payload.data) {
    throw new Error(payload.detail || payload.message || "资料列表加载失败");
  }
  return payload.data.items;
}

export async function uploadLibrarySources(files: File[]): Promise<void> {
  const current = await fetchCurrentSession();
  if (!current) throw new Error("请先登录后再添加资料");
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  const response = await fetch(`${LIBRARY_BASE}/sources`, {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      "X-CSRF-Token": current.csrf_token,
    },
    body,
  });
  const payload = (await response
    .json()
    .catch(() => ({}))) as ApiEnvelope<unknown>;
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || "资料入库失败");
  }
}

async function mutateLibrarySource(
  path: string,
  method: "PATCH" | "DELETE",
  body: Record<string, unknown>,
): Promise<void> {
  const current = await fetchCurrentSession();
  if (!current) throw new Error("请先登录后再管理资料");
  const response = await fetch(`${LIBRARY_BASE}${path}`, {
    method,
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRF-Token": current.csrf_token,
    },
    body: JSON.stringify(body),
  });
  const payload = (await response
    .json()
    .catch(() => ({}))) as ApiEnvelope<unknown>;
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || "资料操作失败");
  }
}

export function setLibrarySourceRetrieval(
  sourceId: string,
  enabled: boolean,
): Promise<void> {
  return mutateLibrarySource(
    `/sources/${encodeURIComponent(sourceId)}/retrieval`,
    "PATCH",
    { enabled },
  );
}

export function deleteLibrarySource(sourceId: string): Promise<void> {
  return mutateLibrarySource(
    `/sources/${encodeURIComponent(sourceId)}`,
    "DELETE",
    {},
  );
}
