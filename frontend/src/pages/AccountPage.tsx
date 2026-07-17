import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Clock3,
  Laptop,
  LoaderCircle,
  LocateFixed,
  LogOut,
  MailCheck,
  MapPin,
  MonitorSmartphone,
  RefreshCw,
  ShieldCheck,
  Smartphone,
} from "lucide-react";
import { AuthApiError, fetchActiveSessions, ManagedSession } from "../auth";
import { Button, PageHeading, StatusMark } from "../components/Primitives";
import useAuth from "../useAuth";

type SessionLoadState = "loading" | "ready" | "error";

export default function AccountPage() {
  const { restore, revokeSession, session: currentSession, user } = useAuth();
  const [sessions, setSessions] = useState<ManagedSession[]>([]);
  const [loadState, setLoadState] = useState<SessionLoadState>("loading");
  const [loadError, setLoadError] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");

  const loadSessions = useCallback(
    async (signal?: AbortSignal) => {
      setLoadState("loading");
      setLoadError("");
      try {
        const data = await fetchActiveSessions(signal);
        setSessions(data.sessions);
        setLoadState("ready");
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError")
          return;
        if (error instanceof AuthApiError && error.status === 401) {
          await restore();
          return;
        }
        setLoadError(
          error instanceof AuthApiError
            ? error.message
            : "暂时无法读取登录设备，请稍后重试",
        );
        setLoadState("error");
      }
    },
    [restore],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadSessions(controller.signal);
    return () => controller.abort();
  }, [loadSessions]);

  const handleRevoke = async (managedSession: ManagedSession) => {
    setRevokingId(managedSession.id);
    setActionError("");
    setActionNotice("");
    try {
      await revokeSession(managedSession.id);
      setSessions((current) =>
        current.filter((item) => item.id !== managedSession.id),
      );
      setConfirmingId(null);
      setActionNotice(`${managedSession.device_label} 已退出登录`);
    } catch (error) {
      if (error instanceof AuthApiError && error.code === "SESSION_NOT_FOUND") {
        setSessions((current) =>
          current.filter((item) => item.id !== managedSession.id),
        );
        setConfirmingId(null);
        setActionNotice("该设备的登录状态已经失效");
      } else if (
        error instanceof AuthApiError &&
        error.code === "CURRENT_SESSION_LOGOUT_REQUIRED"
      ) {
        setActionError("当前设备请使用侧边栏中的退出登录");
      } else {
        setActionError(
          error instanceof AuthApiError
            ? error.message
            : "退出该设备失败，请重试",
        );
      }
    } finally {
      setRevokingId(null);
    }
  };

  const orderedSessions = useMemo(() => {
    return [...sessions].sort((left, right) => {
      if (left.is_current !== right.is_current) return left.is_current ? -1 : 1;
      return Date.parse(right.last_seen_at) - Date.parse(left.last_seen_at);
    });
  }, [sessions]);

  const displayName = user?.display_name || user?.email || "学习用户";
  const avatarLabel = Array.from(displayName.trim())[0] || "学";

  return (
    <div className="page page--wide account-page">
      <PageHeading
        description="查看账户身份和仍可使用的登录设备。"
        eyebrow="账户设置"
        title="账户与登录"
      />

      <section
        className="account-profile"
        aria-labelledby="account-profile-title"
      >
        <div className="account-profile__identity">
          <span className="account-profile__avatar">{avatarLabel}</span>
          <span>
            <small id="account-profile-title">学习账户</small>
            <strong>{displayName}</strong>
            <em>{user?.email}</em>
          </span>
        </div>
        <div className="account-profile__facts">
          <span>
            <MailCheck size={18} />
            <span>
              <small>主邮箱</small>
              <strong>{user?.email_verified ? "已验证" : "等待验证"}</strong>
            </span>
          </span>
          <span>
            <ShieldCheck size={18} />
            <span>
              <small>当前登录</small>
              <strong>{authMethodLabel(currentSession?.auth_method)}</strong>
            </span>
          </span>
        </div>
      </section>

      <section
        className="account-sessions"
        aria-labelledby="active-sessions-title"
      >
        <header className="account-section-heading">
          <div>
            <p className="eyebrow">登录安全</p>
            <h2 id="active-sessions-title">登录设备</h2>
            <p>这里只显示仍然有效的会话。退出其他设备不会影响当前学习进度。</p>
          </div>
          {loadState === "ready" ? (
            <span className="account-session-count">
              {orderedSessions.length} 个有效会话
            </span>
          ) : null}
        </header>

        {actionNotice ? (
          <p className="account-action-notice" role="status">
            <Check size={16} />
            {actionNotice}
          </p>
        ) : null}
        {actionError ? (
          <p className="account-action-error" role="alert">
            {actionError}
          </p>
        ) : null}

        {loadState === "loading" ? <SessionLoading /> : null}
        {loadState === "error" ? (
          <div className="account-session-error" role="alert">
            <span>
              <strong>登录设备读取失败</strong>
              <small>{loadError}</small>
            </span>
            <Button
              icon={<RefreshCw size={16} />}
              onClick={() => void loadSessions()}
              tone="secondary"
            >
              重新加载
            </Button>
          </div>
        ) : null}
        {loadState === "ready" ? (
          <div className="account-session-list">
            {orderedSessions.map((managedSession) => (
              <SessionRow
                confirming={confirmingId === managedSession.id}
                current={managedSession.is_current}
                key={managedSession.id}
                managedSession={managedSession}
                onCancel={() => setConfirmingId(null)}
                onConfirm={() => void handleRevoke(managedSession)}
                onRequestConfirm={() => {
                  setActionError("");
                  setActionNotice("");
                  setConfirmingId(managedSession.id);
                }}
                revoking={revokingId === managedSession.id}
                timezone={user?.timezone}
              />
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}

function SessionRow({
  confirming,
  current,
  managedSession,
  onCancel,
  onConfirm,
  onRequestConfirm,
  revoking,
  timezone,
}: {
  confirming: boolean;
  current: boolean;
  managedSession: ManagedSession;
  onCancel: () => void;
  onConfirm: () => void;
  onRequestConfirm: () => void;
  revoking: boolean;
  timezone?: string;
}) {
  const DeviceIcon = deviceIcon(managedSession.device_label);
  const exactLastSeen = formatDateTime(managedSession.last_seen_at, timezone);

  return (
    <article
      className={`account-session-row ${
        current ? "account-session-row--current" : ""
      }`}
    >
      <span className="account-session-row__device">
        <DeviceIcon size={21} />
      </span>
      <div className="account-session-row__main">
        <span>
          <strong>{managedSession.device_label}</strong>
          {current ? <StatusMark tone="success">当前设备</StatusMark> : null}
        </span>
        <small>
          {authMethodLabel(managedSession.auth_method)} · 创建于{" "}
          {formatDateTime(managedSession.created_at, timezone)}
        </small>
      </div>
      <div className="account-session-row__activity">
        <span title={exactLastSeen}>
          <Clock3 size={15} />
          <span>
            <small>最近活动</small>
            <strong>{formatRelativeTime(managedSession.last_seen_at)}</strong>
          </span>
        </span>
        <span>
          {managedSession.location_label ? (
            <MapPin size={15} />
          ) : (
            <LocateFixed size={15} />
          )}
          <span>
            <small>登录位置</small>
            <strong>{managedSession.location_label || "位置暂不可用"}</strong>
          </span>
        </span>
      </div>
      <div className="account-session-row__actions">
        {current ? (
          <span className="account-session-row__protected">
            <ShieldCheck size={16} />
            正在使用
          </span>
        ) : confirming ? (
          <>
            <Button disabled={revoking} onClick={onCancel} tone="quiet">
              取消
            </Button>
            <Button
              disabled={revoking}
              icon={
                revoking ? (
                  <LoaderCircle className="spin" size={16} />
                ) : (
                  <LogOut size={16} />
                )
              }
              onClick={onConfirm}
              tone="danger"
            >
              确认退出
            </Button>
          </>
        ) : (
          <Button
            icon={<LogOut size={16} />}
            onClick={onRequestConfirm}
            tone="secondary"
          >
            退出此设备
          </Button>
        )}
      </div>
    </article>
  );
}

function SessionLoading() {
  return (
    <div
      aria-label="正在读取登录设备"
      className="account-session-loading"
      role="status"
    >
      {[0, 1].map((item) => (
        <span key={item}>
          <i />
          <i />
          <i />
        </span>
      ))}
    </div>
  );
}

function authMethodLabel(method?: string) {
  const labels: Record<string, string> = {
    password: "邮箱密码",
    github: "GitHub",
    email_verification: "邮箱验证",
  };
  return method ? labels[method] || "安全登录" : "安全登录";
}

function deviceIcon(label: string) {
  const normalized = label.toLowerCase();
  if (
    normalized.includes("iphone") ||
    normalized.includes("android") ||
    normalized.includes("mobile")
  ) {
    return Smartphone;
  }
  if (
    normalized.includes("macos") ||
    normalized.includes("windows") ||
    normalized.includes("linux")
  ) {
    return Laptop;
  }
  return MonitorSmartphone;
}

function formatDateTime(value: string, timezone?: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: timezone || "Asia/Shanghai",
    }).format(date);
  } catch {
    return new Intl.DateTimeFormat("zh-CN", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }
}

function formatRelativeTime(value: string) {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "时间未知";
  const elapsedSeconds = Math.max(
    0,
    Math.floor((Date.now() - timestamp) / 1000),
  );
  if (elapsedSeconds < 60) return "刚刚";
  const elapsedMinutes = Math.floor(elapsedSeconds / 60);
  if (elapsedMinutes < 60) return `${elapsedMinutes} 分钟前`;
  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) return `${elapsedHours} 小时前`;
  const elapsedDays = Math.floor(elapsedHours / 24);
  return `${elapsedDays} 天前`;
}
