"""Replaceable email-delivery boundary for authentication messages."""

from __future__ import annotations

import asyncio
import hashlib
import html
import smtplib
import ssl
from collections import deque
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from typing import Mapping, Protocol

from email_validator import EmailNotValidError, validate_email

from app.core.config import settings


@dataclass(frozen=True)
class AuthEmail:
    """Authentication email queued after the database transaction commits."""

    template_id: str
    recipient: str
    variables: Mapping[str, str]
    idempotency_key: str


@dataclass(frozen=True)
class RenderedAuthEmail:
    """Provider-neutral authentication email content."""

    subject: str
    text_body: str
    html_body: str


class EmailDeliveryUnavailable(RuntimeError):
    """No production email queue or provider is currently available."""


class EmailSender(Protocol):
    """Queue an authentication email without exposing provider details."""

    async def enqueue(self, message: AuthEmail) -> None:
        """Queue one idempotent message for asynchronous delivery."""


class MemoryEmailSender:
    """Bounded development outbox that never writes token values to logs."""

    def __init__(self, capacity: int = 100) -> None:
        self._messages: deque[AuthEmail] = deque(maxlen=capacity)
        self._lock = asyncio.Lock()

    async def enqueue(self, message: AuthEmail) -> None:
        async with self._lock:
            self._messages.append(message)

    async def latest_for(self, recipient: str) -> AuthEmail | None:
        """Return the latest local message for integration tests and tooling."""

        async with self._lock:
            for message in reversed(self._messages):
                if message.recipient == recipient:
                    return message
        return None

    async def clear(self) -> None:
        async with self._lock:
            self._messages.clear()


class SMTPEmailSender:
    """Deliver authentication messages through a configured SMTP relay."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        security: str,
        timeout_seconds: float,
        from_address: str,
        from_name: str,
        reply_to: str,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.security = security
        self.timeout_seconds = timeout_seconds
        self.from_address = from_address
        self.from_name = from_name
        self.reply_to = reply_to

    async def enqueue(self, message: AuthEmail) -> None:
        try:
            rendered = render_auth_email(message)
            email_message = self._build_message(message, rendered)
            await asyncio.to_thread(self._send, email_message)
        except EmailDeliveryUnavailable:
            raise
        except (OSError, smtplib.SMTPException, UnicodeError, ValueError) as exc:
            raise EmailDeliveryUnavailable(
                "authentication email delivery failed"
            ) from exc

    def _build_message(
        self,
        message: AuthEmail,
        rendered: RenderedAuthEmail,
    ) -> EmailMessage:
        email_message = EmailMessage()
        email_message["Subject"] = rendered.subject
        email_message["From"] = formataddr(
            (self.from_name, self.from_address),
        )
        email_message["To"] = message.recipient
        email_message["Date"] = formatdate(localtime=False, usegmt=True)
        message_id = hashlib.sha256(message.idempotency_key.encode("utf-8")).hexdigest()
        message_id_domain = self.from_address.rpartition("@")[2]
        email_message["Message-ID"] = f"<{message_id}@{message_id_domain}>"
        if self.reply_to:
            email_message["Reply-To"] = self.reply_to
        email_message.set_content(rendered.text_body)
        email_message.add_alternative(rendered.html_body, subtype="html")
        return email_message

    def _send(self, email_message: EmailMessage) -> None:
        if self.security == "ssl":
            client = smtplib.SMTP_SSL(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
                context=ssl.create_default_context(),
            )
        else:
            client = smtplib.SMTP(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
            )

        with client:
            if self.security == "starttls":
                client.ehlo()
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if self.username:
                client.login(self.username, self.password)
            client.send_message(email_message)


class UnavailableEmailSender:
    """Fail closed when no non-development email adapter is configured."""

    async def enqueue(self, message: AuthEmail) -> None:
        raise EmailDeliveryUnavailable(
            "authentication email delivery is not configured"
        )


memory_email_sender = MemoryEmailSender()
unavailable_email_sender = UnavailableEmailSender()


def get_email_sender() -> EmailSender:
    """Resolve the configured email adapter for FastAPI dependency injection."""

    backend = settings.AUTH_EMAIL_BACKEND.strip().lower()
    if backend == "memory" and settings.ENV in {
        "development",
        "test",
    }:
        return memory_email_sender
    if backend == "smtp":
        validate_smtp_configuration(
            require_tls=settings.ENV not in {"development", "test"},
        )
        return SMTPEmailSender(
            host=settings.AUTH_SMTP_HOST,
            port=settings.AUTH_SMTP_PORT,
            username=settings.AUTH_SMTP_USERNAME,
            password=settings.AUTH_SMTP_PASSWORD,
            security=settings.AUTH_SMTP_SECURITY.strip().lower(),
            timeout_seconds=settings.AUTH_SMTP_TIMEOUT_SECONDS,
            from_address=settings.AUTH_EMAIL_FROM_ADDRESS,
            from_name=settings.AUTH_EMAIL_FROM_NAME,
            reply_to=settings.AUTH_EMAIL_REPLY_TO,
        )
    return unavailable_email_sender


def validate_smtp_configuration(*, require_tls: bool) -> None:
    """Reject incomplete or unsafe SMTP settings before serving traffic."""

    if not settings.AUTH_SMTP_HOST.strip():
        raise RuntimeError("AUTH_SMTP_HOST must be configured for SMTP email")
    if not 1 <= settings.AUTH_SMTP_PORT <= 65535:
        raise RuntimeError("AUTH_SMTP_PORT must be between 1 and 65535")
    if settings.AUTH_SMTP_TIMEOUT_SECONDS <= 0:
        raise RuntimeError("AUTH_SMTP_TIMEOUT_SECONDS must be positive")

    security = settings.AUTH_SMTP_SECURITY.strip().lower()
    if security not in {"starttls", "ssl", "plain"}:
        raise RuntimeError("AUTH_SMTP_SECURITY must be starttls, ssl, or plain")
    if require_tls and security == "plain":
        raise RuntimeError("AUTH_SMTP_SECURITY must enable TLS in production")

    username_configured = bool(settings.AUTH_SMTP_USERNAME)
    password_configured = bool(settings.AUTH_SMTP_PASSWORD)
    if username_configured != password_configured:
        raise RuntimeError(
            "AUTH_SMTP_USERNAME and AUTH_SMTP_PASSWORD " "must be configured together"
        )

    _validate_email_setting(
        "AUTH_EMAIL_FROM_ADDRESS",
        settings.AUTH_EMAIL_FROM_ADDRESS,
        required=True,
    )
    _validate_email_setting(
        "AUTH_EMAIL_REPLY_TO",
        settings.AUTH_EMAIL_REPLY_TO,
        required=False,
    )


def render_auth_email(message: AuthEmail) -> RenderedAuthEmail:
    """Render supported authentication templates as text and HTML."""

    if message.template_id == "verify-email":
        code = _required_variable(message, "code")
        verification_url = _required_variable(message, "verification_url")
        return RenderedAuthEmail(
            subject="验证你的 408 学习工作台邮箱",
            text_body=(
                "你好，\n\n"
                f"你的邮箱验证码是：{code}\n"
                "验证码仅用于本次注册验证。\n\n"
                "也可以打开下面的链接完成验证：\n"
                f"{verification_url}\n\n"
                "如果不是你本人操作，请忽略这封邮件。"
            ),
            html_body=_auth_email_html(
                eyebrow="EMAIL VERIFICATION / 邮箱验证",
                title="验证你的邮箱",
                description="输入下面的 6 位数字码，或直接打开验证链接。",
                code=code,
                action_label="验证邮箱",
                action_url=verification_url,
                footnote="如果不是你本人操作，请忽略这封邮件。",
            ),
        )

    if message.template_id == "reset-password":
        reset_url = _required_variable(message, "reset_url")
        return RenderedAuthEmail(
            subject="重置你的 408 学习工作台密码",
            text_body=(
                "你好，\n\n"
                "请打开下面的限时链接重置密码：\n"
                f"{reset_url}\n\n"
                "该链接只能使用一次。\n"
                "如果不是你本人操作，请忽略这封邮件。"
            ),
            html_body=_auth_email_html(
                eyebrow="ACCOUNT RECOVERY / 账户恢复",
                title="重置你的密码",
                description="打开下面的限时链接，为学习账户设置新密码。",
                action_label="重置密码",
                action_url=reset_url,
                footnote="该链接只能使用一次。如果不是你本人操作，请忽略这封邮件。",
            ),
        )

    if message.template_id == "password-changed":
        return RenderedAuthEmail(
            subject="你的 408 学习工作台密码已更新",
            text_body=(
                "你好，\n\n"
                "你的账户密码已成功更新，其他设备上的旧会话已经退出。\n\n"
                "如果这不是你本人的操作，请立即联系支持人员。"
            ),
            html_body=_auth_email_html(
                eyebrow="SECURITY NOTICE / 安全通知",
                title="密码已更新",
                description="你的账户密码已成功更新，其他设备上的旧会话已经退出。",
                footnote="如果这不是你本人的操作，请立即联系支持人员。",
            ),
        )

    raise EmailDeliveryUnavailable(
        f"unsupported authentication email template: {message.template_id}"
    )


def _auth_email_html(
    *,
    eyebrow: str,
    title: str,
    description: str,
    footnote: str,
    code: str = "",
    action_label: str = "",
    action_url: str = "",
) -> str:
    escaped_eyebrow = html.escape(eyebrow)
    escaped_title = html.escape(title)
    escaped_description = html.escape(description)
    escaped_footnote = html.escape(footnote)
    escaped_code = html.escape(code)
    escaped_action_label = html.escape(action_label)
    escaped_action_url = html.escape(action_url, quote=True)
    code_markup = ""
    if escaped_code:
        code_markup = f"""
          <div style="margin:26px 0 22px;padding:18px 20px;background:#f2f6f2;border:1px solid #d7e2dc;text-align:center;">
            <div style="font-size:13px;color:#617168;margin-bottom:8px;">6 位验证码</div>
            <div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:30px;font-weight:700;letter-spacing:8px;color:#17231d;">{escaped_code}</div>
          </div>
        """
    action_markup = ""
    if escaped_action_url:
        action_markup = f"""
          <div style="margin:24px 0;">
            <a href="{escaped_action_url}" style="display:inline-block;padding:12px 22px;background:#17231d;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;">{escaped_action_label}</a>
          </div>
          <div style="font-size:12px;line-height:1.7;color:#738078;word-break:break-all;">{escaped_action_url}</div>
        """

    return f"""<!doctype html>
<html lang="zh-CN">
  <body style="margin:0;padding:0;background:#edf1ed;color:#17231d;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#edf1ed;padding:28px 14px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;background:#ffffff;border:1px solid #d6ded8;">
            <tr>
              <td style="padding:22px 30px;border-bottom:3px solid #2f6f62;">
                <div style="font-family:Georgia,'Times New Roman',serif;font-size:24px;font-weight:700;color:#2f6f62;">408 <span style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;font-size:16px;color:#17231d;">学习工作台</span></div>
              </td>
            </tr>
            <tr>
              <td style="padding:34px 30px 30px;">
                <div style="font-size:12px;font-weight:700;color:#2f6f62;">{escaped_eyebrow}</div>
                <h1 style="margin:10px 0 12px;font-family:Georgia,'Times New Roman','Songti SC',serif;font-size:28px;line-height:1.3;color:#17231d;">{escaped_title}</h1>
                <p style="margin:0;font-size:15px;line-height:1.8;color:#4e5c54;">{escaped_description}</p>
                {code_markup}
                {action_markup}
                <p style="margin:28px 0 0;padding-top:20px;border-top:1px solid #e0e6e1;font-size:13px;line-height:1.7;color:#738078;">{escaped_footnote}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _required_variable(message: AuthEmail, name: str) -> str:
    value = message.variables.get(name, "").strip()
    if not value:
        raise EmailDeliveryUnavailable(
            f"{message.template_id} email is missing variable: {name}"
        )
    return value


def _validate_email_setting(
    name: str,
    value: str,
    *,
    required: bool,
) -> None:
    candidate = value.strip()
    if not candidate:
        if required:
            raise RuntimeError(f"{name} must be configured for SMTP email")
        return
    try:
        validate_email(candidate, check_deliverability=False)
    except EmailNotValidError as exc:
        raise RuntimeError(f"{name} must be a valid email address") from exc
