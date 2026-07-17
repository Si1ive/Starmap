import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Clock3,
  GitBranch,
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
import {
  AuthApiError,
  fetchActiveSessions,
  fetchGitHubLinkStatus,
  GitHubLinkStatus,
  ManagedSession,
} from "../auth";
import { Button, PageHeading, StatusMark } from "../components/Primitives";
import useAuth from "../useAuth";

type SessionLoadState = "loading" | "ready" | "error";
type ConnectionLoadState = "loading" | "ready" | "error";

export default function AccountPage() {
  const {
    restore,
    revokeSession,
    session: currentSession,
    startGitHubLink,
    user,
  } = useAuth();
  const [sessions, setSessions] = useState<ManagedSession[]>([]);
  const [loadState, setLoadState] = useState<SessionLoadState>("loading");
  const [loadError, setLoadError] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [githubLink, setGitHubLink] = useState<GitHubLinkStatus | null>(null);
  const [connectionLoadState, setConnectionLoadState] =
    useState<ConnectionLoadState>("loading");
  const [connectionError, setConnectionError] = useState("");
  const [githubLinking, setGitHubLinking] = useState(false);

  const loadGitHubLink = useCallback(
    async (signal?: AbortSignal) => {
      setConnectionLoadState("loading");
      setConnectionError("");
      try {
        setGitHubLink(await fetchGitHubLinkStatus(signal));
        setConnectionLoadState("ready");
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError")
          return;
        if (error instanceof AuthApiError && error.status === 401) {
          await restore();
          return;
        }
        setConnectionError(
          error instanceof AuthApiError
            ? error.message
            : "暂时无法读取账号绑定状态",
        );
        setConnectionLoadState("error");
      }
    },
    [restore],
  );

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
    void loadGitHubLink(controller.signal);
    return () => controller.abort();
  }, [loadGitHubLink, loadSessions]);

  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    const linked = search.get("github") === "linked";
    const oauthError = search.get("oauth_error");
    if (!linked && !oauthError) return;

    if (linked) {
      setActionNotice("GitHub 账号已绑定，现在可以用于登录");
      void loadGitHubLink();
    } else if (oauthError) {
      setActionError(githubLinkErrorMessage(oauthError));
    }
    search.delete("github");
    search.delete("oauth_error");
    search.delete("return_path");
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${
        search.toString() ? `?${search.toString()}` : ""
      }${window.location.hash}`,
    );
  }, [loadGitHubLink]);

  const handleGitHubLink = async () => {
    setActionError("");
    setActionNotice("");
    setGitHubLinking(true);
    try {
      const authorization = await startGitHubLink();
      window.location.assign(authorization.authorization_url);
    } catch (error) {
      setActionError(
        error instanceof AuthApiError
          ? error.message
          : "GitHub 绑定请求失败，请稍后重试",
      );
      setGitHubLinking(false);
    }
  };

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
        className="account-connections"
        aria-labelledby="account-connections-title"
      >
        <header className="account-section-heading">
          <div>
            <p className="eyebrow">账号绑定</p>
            <h2 id="account-connections-title">登录方式</h2>
            <p>绑定第三方账号后，可以使用对应方式登录同一个学习账户。</p>
          </div>
        </header>

        <div className="account-connection-row">
          <span className="account-connection-row__icon">
            <GitBranch size={21} />
          </span>
          <div className="account-connection-row__main">
            <strong>GitHub</strong>
            <small>
              {connectionLoadState === "loading"
                ? "正在确认绑定状态"
                : connectionLoadState === "error"
                  ? connectionError
                  : githubLink?.linked
                    ? githubIdentityLabel(githubLink)
                    : "尚未绑定"}
            </small>
          </div>
          <div className="account-connection-row__status">
            {connectionLoadState === "ready" && githubLink?.linked ? (
              <StatusMark tone="success">已绑定</StatusMark>
            ) : null}
          </div>
          <Button
            disabled={
              connectionLoadState !== "ready" ||
              Boolean(githubLink?.linked) ||
              githubLinking
            }
            icon={
              githubLinking || connectionLoadState === "loading" ? (
                <LoaderCircle className="spin" size={16} />
              ) : (
                <GitBranch size={16} />
              )
            }
            onClick={() => void handleGitHubLink()}
            tone="secondary"
          >
            {githubLinking
              ? "正在前往 GitHub"
              : githubLink?.linked
                ? "已绑定"
                : "绑定 GitHub"}
          </Button>
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

function githubIdentityLabel(identity: GitHubLinkStatus) {
  if (identity.username) return `已连接 @${identity.username}`;
  if (identity.email) return `已连接 ${identity.email}`;
  return "已连接 GitHub 账号";
}

function githubLinkErrorMessage(code: string) {
  const messages: Record<string, string> = {
    GITHUB_OAUTH_CANCELLED: "你已取消 GitHub 授权，账号绑定没有变化",
    GITHUB_OAUTH_STATE_INVALID: "GitHub 绑定请求已失效，请重新发起",
    GITHUB_OAUTH_UNAVAILABLE: "GitHub 暂时不可用，请稍后重试",
    GITHUB_LINK_AUTH_REQUIRED: "登录状态已变化，请重新登录后绑定 GitHub",
    GITHUB_IDENTITY_IN_USE: "该 GitHub 账号已绑定其他学习账户",
    GITHUB_ALREADY_LINKED: "当前学习账户已经绑定 GitHub",
  };
  return messages[code] || "GitHub 绑定未完成，请重新发起";
}
