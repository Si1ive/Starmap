import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Check,
  Clock3,
  GitBranch,
  KeyRound,
  Laptop,
  LoaderCircle,
  LocateFixed,
  LogOut,
  Mail,
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
    confirmEmailLink,
    restore,
    revokeSession,
    session: currentSession,
    startEmailLink,
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
  const [emailFormOpen, setEmailFormOpen] = useState(false);
  const [emailStep, setEmailStep] = useState<"details" | "code">("details");
  const [email, setEmail] = useState(user?.email || "");
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [emailCode, setEmailCode] = useState("");
  const [emailSubmitting, setEmailSubmitting] = useState(false);
  const [emailCountdown, setEmailCountdown] = useState(0);
  const emailLinkConfirmationStarted = useRef(false);

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
    if (!emailFormOpen && user?.email) setEmail(user.email);
  }, [emailFormOpen, user?.email]);

  useEffect(() => {
    if (emailCountdown <= 0) return undefined;
    const timer = window.setInterval(() => {
      setEmailCountdown((current) => Math.max(0, current - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [emailCountdown]);

  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    const emailToken = search.get("email_token");
    if (!emailToken || emailLinkConfirmationStarted.current) return;
    emailLinkConfirmationStarted.current = true;
    search.delete("email_token");
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${
        search.toString() ? `?${search.toString()}` : ""
      }${window.location.hash}`,
    );

    setActionError("");
    setActionNotice("");
    setEmailSubmitting(true);
    void confirmEmailLink({ token: emailToken })
      .then((result) => {
        setActionNotice(`${result.email} 已绑定，现在可以使用邮箱和密码登录`);
        setEmailFormOpen(false);
      })
      .catch((error) => {
        setActionError(emailLinkErrorMessage(error));
      })
      .finally(() => setEmailSubmitting(false));
  }, [confirmEmailLink]);

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

  const sendEmailLink = async () => {
    if (password !== passwordConfirmation) {
      setActionError("两次输入的密码不一致");
      return;
    }
    setActionError("");
    setActionNotice("");
    setEmailSubmitting(true);
    try {
      const result = await startEmailLink({
        email,
        password,
        password_confirmation: passwordConfirmation,
      });
      setEmailStep("code");
      setEmailCode("");
      setEmailCountdown(Math.max(0, result.resend_after_seconds));
      setActionNotice(`确认邮件已发送到 ${email}`);
    } catch (error) {
      setActionError(emailLinkErrorMessage(error));
    } finally {
      setEmailSubmitting(false);
    }
  };

  const handleStartEmailLink = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void sendEmailLink();
  };

  const handleConfirmEmailLink = async (
    event: FormEvent<HTMLFormElement>,
  ) => {
    event.preventDefault();
    if (!/^\d{6}$/.test(emailCode)) {
      setActionError("请输入邮件中的 6 位数字验证码");
      return;
    }
    setActionError("");
    setActionNotice("");
    setEmailSubmitting(true);
    try {
      const result = await confirmEmailLink({ code: emailCode });
      setActionNotice(`${result.email} 已绑定，现在可以使用邮箱和密码登录`);
      setEmailFormOpen(false);
      setEmailStep("details");
      setPassword("");
      setPasswordConfirmation("");
      setEmailCode("");
    } catch (error) {
      setActionError(emailLinkErrorMessage(error));
    } finally {
      setEmailSubmitting(false);
    }
  };

  const openEmailForm = () => {
    setActionError("");
    setActionNotice("");
    setEmail(user?.email || "");
    setEmailStep("details");
    setEmailCode("");
    setEmailFormOpen(true);
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
        setActionError("当前设备请使用右上角账户菜单中的退出登录");
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
        description="管理登录方式和仍可使用的登录设备。"
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
            <em>
              {user?.email} ·{" "}
              {user?.email_login_enabled ? "登录邮箱" : "联系邮箱"}
            </em>
          </span>
        </div>
        <div className="account-profile__facts">
          <span>
            <MailCheck size={18} />
            <span>
              <small>
                {user?.email_login_enabled ? "登录邮箱" : "联系邮箱"}
              </small>
              <strong>
                {user?.email_login_enabled ? "邮箱登录已启用" : "邮箱登录未绑定"}
              </strong>
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

      <section
        className="account-connections"
        aria-labelledby="account-connections-title"
      >
        <header className="account-section-heading">
          <div>
            <p className="eyebrow">账号绑定</p>
            <h2 id="account-connections-title">登录方式</h2>
            <p>完成对应方式的验证后，才会标记为已绑定并允许登录。</p>
          </div>
        </header>

        <div className="account-connection-row">
          <span className="account-connection-row__icon account-connection-row__icon--email">
            <Mail size={21} />
          </span>
          <div className="account-connection-row__main">
            <strong>邮箱与密码</strong>
            <small>
              {user?.email_login_enabled
                ? `已绑定 ${user.email}`
                : currentSession?.auth_method === "github"
                  ? `${user?.email} 来自 GitHub，目前仅作为联系邮箱`
                  : "尚未启用邮箱密码登录"}
            </small>
          </div>
          <div className="account-connection-row__status">
            {user?.email_login_enabled ? (
              <StatusMark tone="success">已绑定</StatusMark>
            ) : (
              <StatusMark tone="neutral">未绑定</StatusMark>
            )}
          </div>
          <Button
            disabled={Boolean(user?.email_login_enabled) || emailSubmitting}
            icon={
              emailSubmitting ? (
                <LoaderCircle className="spin" size={16} />
              ) : (
                <KeyRound size={16} />
              )
            }
            onClick={openEmailForm}
            tone="secondary"
          >
            {user?.email_login_enabled ? "已启用" : "绑定邮箱"}
          </Button>
        </div>

        {emailFormOpen && !user?.email_login_enabled ? (
          emailStep === "details" ? (
            <form
              className="account-email-form"
              onSubmit={handleStartEmailLink}
            >
              <header>
                <div>
                  <strong>启用邮箱登录</strong>
                  <small>验证邮箱所有权后，这组邮箱和密码才可用于登录。</small>
                </div>
                <Button
                  disabled={emailSubmitting}
                  onClick={() => setEmailFormOpen(false)}
                  tone="quiet"
                >
                  取消
                </Button>
              </header>
              <div className="account-email-form__fields">
                <label>
                  <span>登录邮箱</span>
                  <div>
                    <Mail size={17} />
                    <input
                      autoComplete="email"
                      autoCapitalize="none"
                      inputMode="email"
                      onChange={(event) => setEmail(event.target.value)}
                      required
                      spellCheck={false}
                      type="text"
                      value={email}
                    />
                  </div>
                </label>
                <label>
                  <span>设置密码</span>
                  <div>
                    <KeyRound size={17} />
                    <input
                      autoComplete="new-password"
                      minLength={15}
                      onChange={(event) => setPassword(event.target.value)}
                      placeholder="至少 15 位字符"
                      required
                      type="password"
                      value={password}
                    />
                  </div>
                </label>
                <label>
                  <span>确认密码</span>
                  <div>
                    <KeyRound size={17} />
                    <input
                      autoComplete="new-password"
                      minLength={15}
                      onChange={(event) =>
                        setPasswordConfirmation(event.target.value)
                      }
                      required
                      type="password"
                      value={passwordConfirmation}
                    />
                  </div>
                </label>
              </div>
              <div className="account-email-form__actions">
                <Button
                  disabled={emailSubmitting}
                  icon={
                    emailSubmitting ? (
                      <LoaderCircle className="spin" size={16} />
                    ) : (
                      <MailCheck size={16} />
                    )
                  }
                  type="submit"
                >
                  {emailSubmitting ? "正在发送" : "发送验证码"}
                </Button>
              </div>
            </form>
          ) : (
            <form
              className="account-email-form"
              onSubmit={handleConfirmEmailLink}
            >
              <header>
                <div>
                  <strong>确认邮箱</strong>
                  <small>确认邮件已发送到 {email}</small>
                </div>
                <Button
                  disabled={emailSubmitting}
                  onClick={() => setEmailStep("details")}
                  tone="quiet"
                >
                  修改信息
                </Button>
              </header>
              <label className="account-email-form__code">
                <span>6 位验证码</span>
                <input
                  autoComplete="one-time-code"
                  inputMode="numeric"
                  maxLength={6}
                  onChange={(event) =>
                    setEmailCode(event.target.value.replace(/\D/g, ""))
                  }
                  placeholder="000000"
                  value={emailCode}
                />
              </label>
              <div className="account-email-form__actions account-email-form__actions--split">
                <Button
                  disabled={emailCountdown > 0 || emailSubmitting}
                  onClick={() => void sendEmailLink()}
                  tone="secondary"
                >
                  {emailCountdown > 0
                    ? `${emailCountdown} 秒后可重发`
                    : "重新发送"}
                </Button>
                <Button
                  disabled={emailSubmitting || emailCode.length !== 6}
                  icon={
                    emailSubmitting ? (
                      <LoaderCircle className="spin" size={16} />
                    ) : (
                      <Check size={16} />
                    )
                  }
                  type="submit"
                >
                  {emailSubmitting ? "正在确认" : "确认绑定"}
                </Button>
              </div>
            </form>
          )
        ) : null}

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

function emailLinkErrorMessage(error: unknown) {
  if (!(error instanceof AuthApiError)) {
    return "邮箱绑定请求失败，请稍后重试";
  }
  const messages: Record<string, string> = {
    EMAIL_LOGIN_ALREADY_ENABLED: "当前账户已经启用邮箱登录",
    EMAIL_LINK_UNAVAILABLE: "该邮箱无法绑定到当前账户",
    EMAIL_LINK_INVALID: "验证码无效或已过期，请重新发送",
    PASSWORD_TOO_SHORT: "密码长度不足，请设置至少 15 位字符",
    PASSWORD_TOO_LONG: "密码过长，请使用不超过 128 位字符",
    AUTHENTICATION_REQUIRED: "登录状态已变化，请重新登录后绑定邮箱",
    CSRF_INVALID: "登录状态已变化，请刷新页面后重试",
  };
  if (error.code === "AUTH_RATE_LIMITED" && error.retryAfterSeconds) {
    return `操作过于频繁，请在 ${error.retryAfterSeconds} 秒后重试`;
  }
  return messages[error.code] || error.message;
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
