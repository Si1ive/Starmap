import smtplib

import pytest

from app.core.config import settings
from app.modules.identity.email import (
    AuthEmail,
    EmailDeliveryUnavailable,
    SMTPEmailSender,
    get_email_sender,
    render_auth_email,
    validate_smtp_configuration,
)


def verification_message(**variables: str) -> AuthEmail:
    return AuthEmail(
        template_id="verify-email",
        recipient="learner@example.com",
        variables={
            "code": "123456",
            "verification_url": "https://learn.example.com/verify?token=test",
            **variables,
        },
        idempotency_key="verify-email:test",
    )


def test_verification_email_renders_branded_text_and_escaped_html():
    rendered = render_auth_email(
        verification_message(
            verification_url=("https://learn.example.com/verify?token=a&next=<profile>")
        )
    )

    assert rendered.subject == "验证你的 408 学习工作台邮箱"
    assert "123456" in rendered.text_body
    assert ">408 <" in rendered.html_body
    assert ">学习工作台<" in rendered.html_body
    assert "token=a&amp;next=&lt;profile&gt;" in rendered.html_body
    assert "token=a&next=<profile>" not in rendered.html_body


def test_email_link_message_requires_verification_before_claiming_binding():
    rendered = render_auth_email(
        AuthEmail(
            template_id="link-email",
            recipient="learner@example.com",
            variables={
                "code": "654321",
                "verification_url": "https://learn.example.com/account?email_token=test",
            },
            idempotency_key="link-email:test",
        )
    )

    assert rendered.subject == "确认绑定你的 408 学习工作台邮箱"
    assert "654321" in rendered.text_body
    assert "仅用于启用邮箱密码登录" in rendered.text_body
    assert "确认绑定" in rendered.html_body


@pytest.mark.asyncio
async def test_smtp_sender_uses_starttls_auth_and_multipart_email(monkeypatch):
    smtp_sessions = []

    class FakeSMTP:
        def __init__(self, host, port, *, timeout):
            self.host = host
            self.port = port
            self.timeout = timeout
            self.events = []
            self.message = None
            smtp_sessions.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def ehlo(self):
            self.events.append("ehlo")

        def starttls(self, *, context):
            assert context is not None
            self.events.append("starttls")

        def login(self, username, password):
            self.events.append(("login", username, password))

        def send_message(self, message):
            self.events.append("send")
            self.message = message

    monkeypatch.setattr(
        "app.modules.identity.email.smtplib.SMTP",
        FakeSMTP,
    )
    sender = SMTPEmailSender(
        host="smtp.example.com",
        port=587,
        username="smtp-user",
        password="smtp-password",
        security="starttls",
        timeout_seconds=5,
        from_address="no-reply@example.com",
        from_name="408 学习工作台",
        reply_to="support@example.com",
    )

    await sender.enqueue(verification_message())

    session = smtp_sessions[0]
    assert (session.host, session.port, session.timeout) == (
        "smtp.example.com",
        587,
        5,
    )
    assert session.events == [
        "ehlo",
        "starttls",
        "ehlo",
        ("login", "smtp-user", "smtp-password"),
        "send",
    ]
    assert session.message["To"] == "learner@example.com"
    assert session.message["Reply-To"] == "support@example.com"
    assert "408 学习工作台" in str(session.message["From"])
    assert "123456" in session.message.get_body(preferencelist=("plain",)).get_content()
    assert (
        "<!doctype html>"
        in session.message.get_body(preferencelist=("html",)).get_content()
    )
    assert (
        session.message["Message-ID"]
        == "<19dbb611d610e340a4a564a1812e4d185978d64fe93c88ba73c719a84e934e6d"
        "@example.com>"
    )


@pytest.mark.asyncio
async def test_smtp_sender_supports_implicit_tls_without_starttls(monkeypatch):
    smtp_sessions = []

    class FakeSMTPSSL:
        def __init__(self, host, port, *, timeout, context):
            self.host = host
            self.port = port
            self.timeout = timeout
            self.context = context
            self.events = []
            smtp_sessions.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def send_message(self, message):
            self.events.append(("send", message["To"]))

    monkeypatch.setattr(
        "app.modules.identity.email.smtplib.SMTP_SSL",
        FakeSMTPSSL,
    )
    sender = SMTPEmailSender(
        host="smtp.example.com",
        port=465,
        username="",
        password="",
        security="ssl",
        timeout_seconds=5,
        from_address="no-reply@example.com",
        from_name="408 学习工作台",
        reply_to="",
    )

    await sender.enqueue(verification_message())

    session = smtp_sessions[0]
    assert (session.host, session.port, session.timeout) == (
        "smtp.example.com",
        465,
        5,
    )
    assert session.context is not None
    assert session.events == [("send", "learner@example.com")]


@pytest.mark.asyncio
async def test_smtp_sender_hides_provider_failures(monkeypatch):
    def fail_to_connect(*args, **kwargs):
        raise smtplib.SMTPConnectError(421, "provider unavailable")

    monkeypatch.setattr(
        "app.modules.identity.email.smtplib.SMTP",
        fail_to_connect,
    )
    sender = SMTPEmailSender(
        host="smtp.example.com",
        port=587,
        username="",
        password="",
        security="starttls",
        timeout_seconds=5,
        from_address="no-reply@example.com",
        from_name="408 学习工作台",
        reply_to="",
    )

    with pytest.raises(
        EmailDeliveryUnavailable,
        match="authentication email delivery failed",
    ):
        await sender.enqueue(verification_message())


def test_production_smtp_configuration_requires_tls(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "AUTH_SMTP_PORT", 25)
    monkeypatch.setattr(settings, "AUTH_SMTP_USERNAME", "")
    monkeypatch.setattr(settings, "AUTH_SMTP_PASSWORD", "")
    monkeypatch.setattr(settings, "AUTH_SMTP_SECURITY", "plain")
    monkeypatch.setattr(settings, "AUTH_SMTP_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(
        settings,
        "AUTH_EMAIL_FROM_ADDRESS",
        "no-reply@example.com",
    )
    monkeypatch.setattr(settings, "AUTH_EMAIL_REPLY_TO", "")

    with pytest.raises(RuntimeError, match="must enable TLS"):
        validate_smtp_configuration(require_tls=True)


def test_get_email_sender_uses_validated_smtp_settings(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "AUTH_EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(settings, "AUTH_SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "AUTH_SMTP_PORT", 465)
    monkeypatch.setattr(settings, "AUTH_SMTP_USERNAME", "smtp-user")
    monkeypatch.setattr(settings, "AUTH_SMTP_PASSWORD", "smtp-password")
    monkeypatch.setattr(settings, "AUTH_SMTP_SECURITY", "ssl")
    monkeypatch.setattr(settings, "AUTH_SMTP_TIMEOUT_SECONDS", 8)
    monkeypatch.setattr(
        settings,
        "AUTH_EMAIL_FROM_ADDRESS",
        "no-reply@example.com",
    )
    monkeypatch.setattr(settings, "AUTH_EMAIL_FROM_NAME", "408 学习工作台")
    monkeypatch.setattr(settings, "AUTH_EMAIL_REPLY_TO", "support@example.com")

    sender = get_email_sender()

    assert isinstance(sender, SMTPEmailSender)
    assert sender.host == "smtp.example.com"
    assert sender.port == 465
    assert sender.security == "ssl"
    assert sender.timeout_seconds == 8
    assert sender.from_address == "no-reply@example.com"
    assert sender.reply_to == "support@example.com"
