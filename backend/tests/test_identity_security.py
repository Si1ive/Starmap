import pytest

from app.core.config import settings
from app.modules.identity.anti_bot import (
    AntiBotUnavailable,
    DevelopmentAntiBotVerifier,
    UnavailableAntiBotVerifier,
)
from app.modules.identity.email import (
    AuthEmail,
    EmailDeliveryUnavailable,
    MemoryEmailSender,
    UnavailableEmailSender,
)
from app.modules.identity.rate_limit import (
    AuthRateLimiter,
    RateLimitBucket,
    RateLimitExceeded,
    progressive_delay_seconds,
)
from app.modules.identity.security import (
    DEVELOPMENT_ACTION_TOKEN_SECRET,
    PasswordPolicyError,
    PasswordService,
    action_token_digest,
    csrf_token_digest,
    derive_csrf_token,
    generate_opaque_token,
    generate_verification_code,
    identifier_digest,
    infer_device_label,
    normalize_email,
    pack_ip_address,
    sanitize_user_agent,
    session_token_digest,
    validate_user_auth_security_config,
)


def test_password_service_uses_argon2id_and_rejects_invalid_passwords():
    service = PasswordService()
    password = "correct horse battery staple"
    password_hash = service.hash_password(password)

    assert password_hash.startswith("$argon2id$")
    assert service.verify_password(password, password_hash).valid
    assert not service.verify_password("wrong password value", password_hash).valid
    assert not service.verify_password(password, None).valid

    with pytest.raises(PasswordPolicyError) as short_error:
        service.hash_password("too short")
    assert short_error.value.code == "PASSWORD_TOO_SHORT"

    with pytest.raises(PasswordPolicyError) as common_error:
        service.hash_password("passwordpassword")
    assert common_error.value.code == "PASSWORD_TOO_COMMON"

    with pytest.raises(PasswordPolicyError) as encoding_error:
        service.hash_password("valid length \ud800 password")
    assert encoding_error.value.code == "PASSWORD_INVALID_ENCODING"


def test_email_and_token_primitives_are_deterministic_without_plaintext_storage():
    normalized, display = normalize_email(" Alice@Example.COM ")
    session_token = generate_opaque_token()
    code = generate_verification_code()

    assert normalized == "alice@example.com"
    assert display == "Alice@example.com"
    assert len(session_token_digest(session_token)) == 32
    assert code.isdigit()
    assert len(code) == 6

    first = action_token_digest(
        code,
        "verify_email",
        secret="a" * 32,
    )
    second = action_token_digest(
        code,
        "verify_email",
        secret="a" * 32,
    )
    assert first == second
    assert first != action_token_digest(
        code,
        "reset_password",
        secret="a" * 32,
    )
    assert len(identifier_digest(normalized, secret="b" * 32)) == 32


def test_csrf_token_is_derived_from_session_and_persisted_as_digest():
    token = generate_opaque_token()
    csrf_token = derive_csrf_token(token, secret="c" * 32)

    assert csrf_token == derive_csrf_token(token, secret="c" * 32)
    assert csrf_token != derive_csrf_token(
        generate_opaque_token(),
        secret="c" * 32,
    )
    assert len(csrf_token_digest(csrf_token)) == 32


def test_request_metadata_is_bounded_and_non_identifying():
    assert len(pack_ip_address("127.0.0.1")) == 4
    assert len(pack_ip_address("2001:db8::1")) == 16
    assert pack_ip_address("not-an-ip") is None

    user_agent = "Mozilla/5.0 (Macintosh) Chrome/126.0\x00"
    assert sanitize_user_agent(user_agent).endswith("Chrome/126.0")
    assert infer_device_label(user_agent) == "Chrome on macOS"
    assert len(sanitize_user_agent("x" * 600)) == 512


@pytest.mark.asyncio
async def test_local_email_and_anti_bot_adapters_preserve_production_boundaries():
    sender = MemoryEmailSender(capacity=2)
    message = AuthEmail(
        template_id="verify-email",
        recipient="user@example.com",
        variables={"code": "123456"},
        idempotency_key="verification:test",
    )
    await sender.enqueue(message)
    assert await sender.latest_for("user@example.com") == message

    decision = await DevelopmentAntiBotVerifier().verify(
        None,
        action="register",
        remote_ip="127.0.0.1",
    )
    assert decision.allowed

    with pytest.raises(EmailDeliveryUnavailable):
        await UnavailableEmailSender().enqueue(message)
    with pytest.raises(AntiBotUnavailable):
        await UnavailableAntiBotVerifier().verify(
            None,
            action="register",
            remote_ip="127.0.0.1",
        )


@pytest.mark.asyncio
async def test_rate_limiter_enforces_independent_local_buckets():
    now = [1000.0]
    limiter = AuthRateLimiter(clock=lambda: now[0])
    bucket = RateLimitBucket(
        dimension="identifier",
        value="user@example.com",
        limit=2,
        window_seconds=60,
    )

    await limiter.enforce("login", [bucket])
    await limiter.enforce("login", [bucket])
    with pytest.raises(RateLimitExceeded) as blocked:
        await limiter.enforce("login", [bucket])
    assert blocked.value.dimension == "identifier"
    assert blocked.value.retry_after == 60

    now[0] += 61
    await limiter.enforce("login", [bucket])


@pytest.mark.asyncio
async def test_login_failure_delay_progresses_and_account_count_can_clear():
    limiter = AuthRateLimiter(clock=lambda: 1000.0)

    delays = [
        await limiter.record_login_failure(
            identifier="user@example.com",
            remote_ip="127.0.0.1",
        )
        for _ in range(5)
    ]
    assert delays == [0.0, 0.0, 0.25, 0.5, 1.0]
    assert progressive_delay_seconds(20) == 2.0

    await limiter.clear_login_failures(identifier="user@example.com")
    delay = await limiter.record_login_failure(
        identifier="user@example.com",
        remote_ip="192.0.2.1",
    )
    assert delay == 0.0


def test_production_rejects_development_auth_secrets(monkeypatch):
    original_origins = settings.ALLOWED_ORIGINS
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(
        settings,
        "AUTH_ACTION_TOKEN_SECRET",
        DEVELOPMENT_ACTION_TOKEN_SECRET,
    )
    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", original_origins)

    with pytest.raises(RuntimeError, match="AUTH_ACTION_TOKEN_SECRET"):
        validate_user_auth_security_config()
