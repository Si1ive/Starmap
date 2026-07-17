"""Learning-user registration, login, and session endpoints."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.core.config import settings
from app.core.logging import get_logger
from app.db import get_db
from app.middleware.error_handler import APIException
from app.modules.identity.anti_bot import (
    AntiBotUnavailable,
    AntiBotVerifier,
    get_anti_bot_verifier,
)
from app.modules.identity.email import (
    AuthEmail,
    EmailDeliveryUnavailable,
    EmailSender,
    get_email_sender,
)
from app.modules.identity.context import auth_request_context
from app.modules.identity.dependencies import (
    AUTH_NO_STORE_HEADERS,
    get_session_service,
    require_csrf_session,
    require_current_session,
    validate_json_origin,
)
from app.modules.identity.rate_limit import (
    AuthRateLimiter,
    RateLimitBucket,
    RateLimitExceeded,
    get_auth_rate_limiter,
)
from app.modules.identity.registration import (
    RegistrationFlowError,
    RegistrationOutcome,
    RegistrationService,
)
from app.modules.identity.schemas import (
    ConfirmEmailVerificationRequest,
    LoginRequest,
    RegisterRequest,
    ResendEmailVerificationRequest,
)
from app.modules.identity.security import (
    PasswordService,
    get_password_service,
    normalize_email,
    sanitize_user_agent,
)
from app.modules.identity.session import (
    AuthenticatedSession,
    LoginFlowError,
    LoginOutcome,
    LoginService,
    SessionService,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["用户认证"])

GENERIC_REGISTRATION_DATA = {
    "verification_required": True,
    "resend_after_seconds": 60,
}


def get_registration_service(
    db: AsyncSession = Depends(get_db),
    password_service: PasswordService = Depends(get_password_service),
) -> RegistrationService:
    """Build the request-scoped registration service."""

    return RegistrationService(db, password_service)


def get_login_service(
    db: AsyncSession = Depends(get_db),
    password_service: PasswordService = Depends(get_password_service),
    rate_limiter: AuthRateLimiter = Depends(get_auth_rate_limiter),
) -> LoginService:
    """Build the request-scoped password login service."""

    return LoginService(db, password_service, rate_limiter)


@router.post(
    "/login",
    response_model=ApiResponse,
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: LoginService = Depends(get_login_service),
    rate_limiter: AuthRateLimiter = Depends(get_auth_rate_limiter),
) -> ApiResponse:
    """Create a revocable opaque session after password authentication."""

    validate_json_origin(request)
    context = auth_request_context(request)
    identifier = _login_rate_limit_identifier(payload.email)
    device_signal = (
        f"{context.remote_ip or 'unknown'}:"
        f"{sanitize_user_agent(context.user_agent) or 'unknown'}"
    )
    await _enforce_rate_limits(
        rate_limiter,
        "login",
        [
            RateLimitBucket("ip", context.remote_ip or "unknown", 30, 900),
            RateLimitBucket("identifier", identifier, 10, 900),
            RateLimitBucket("device", device_signal, 20, 900),
        ],
    )
    try:
        outcome = await service.login(
            payload,
            context,
            request.cookies.get(settings.AUTH_SESSION_COOKIE_NAME),
        )
    except LoginFlowError as exc:
        raise APIException(
            message=str(exc),
            status_code=exc.status_code,
            code=exc.code,
            headers=AUTH_NO_STORE_HEADERS,
        ) from exc

    _set_session_cookie(response, outcome)
    _clear_registration_cookie(response)
    _harden_auth_response(response)
    return ApiResponse(
        message="登录成功",
        data=_authenticated_data(
            outcome.user,
            outcome.profile,
            outcome.session,
            outcome.csrf_token,
        ),
    )


@router.get(
    "/me",
    response_model=ApiResponse,
)
async def get_current_user(
    response: Response,
    current: AuthenticatedSession = Depends(require_current_session),
) -> ApiResponse:
    """Return the only authoritative browser authentication state."""

    _harden_auth_response(response)
    return ApiResponse(
        data=_authenticated_data(
            current.user,
            current.profile,
            current.session,
            current.csrf_token,
        )
    )


@router.post(
    "/logout",
    response_model=ApiResponse,
)
async def logout(
    request: Request,
    response: Response,
    current: AuthenticatedSession = Depends(require_csrf_session),
    service: SessionService = Depends(get_session_service),
) -> ApiResponse:
    """Revoke the current server-side session and clear its Cookie."""

    await service.logout(current, auth_request_context(request))
    _clear_session_cookie(response)
    _harden_auth_response(response)
    return ApiResponse(
        message="已退出登录",
        data={"authenticated": False},
    )


@router.post(
    "/register",
    response_model=ApiResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    service: RegistrationService = Depends(get_registration_service),
    rate_limiter: AuthRateLimiter = Depends(get_auth_rate_limiter),
    anti_bot: AntiBotVerifier = Depends(get_anti_bot_verifier),
    email_sender: EmailSender = Depends(get_email_sender),
) -> ApiResponse:
    """Create a pending account without exposing email existence."""

    validate_json_origin(request)
    context = auth_request_context(request)
    normalized_email, _ = normalize_email(str(payload.email))
    await _enforce_rate_limits(
        rate_limiter,
        "register",
        [
            RateLimitBucket("ip", context.remote_ip or "unknown", 10, 3600),
            RateLimitBucket("email", normalized_email, 3, 3600),
        ],
    )
    await _verify_anti_bot(
        anti_bot,
        payload.anti_bot_token,
        action="register",
        remote_ip=context.remote_ip,
    )
    try:
        outcome = await service.register(payload, context)
    except RegistrationFlowError as exc:
        raise _api_error(exc) from exc

    _set_registration_cookie(response, outcome.registration_token)
    _harden_auth_response(response)
    await _enqueue_verification(email_sender, outcome)
    return ApiResponse(
        code=status.HTTP_202_ACCEPTED,
        message="如果可以继续注册，我们已发送验证邮件",
        data=GENERIC_REGISTRATION_DATA,
    )


@router.post(
    "/email-verification/resend",
    response_model=ApiResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resend_email_verification(
    payload: ResendEmailVerificationRequest,
    request: Request,
    response: Response,
    service: RegistrationService = Depends(get_registration_service),
    rate_limiter: AuthRateLimiter = Depends(get_auth_rate_limiter),
    anti_bot: AntiBotVerifier = Depends(get_anti_bot_verifier),
    email_sender: EmailSender = Depends(get_email_sender),
) -> ApiResponse:
    """Rotate verification credentials for a valid browser transaction."""

    validate_json_origin(request)
    context = auth_request_context(request)
    registration_token = request.cookies.get(settings.AUTH_REGISTRATION_COOKIE_NAME)
    transaction_dimension = (
        registration_token or f"missing:{context.remote_ip or 'unknown'}"
    )
    await _enforce_rate_limits(
        rate_limiter,
        "verification-resend",
        [
            RateLimitBucket("ip", context.remote_ip or "unknown", 10, 3600),
            RateLimitBucket(
                "transaction-cooldown",
                transaction_dimension,
                1,
                60,
            ),
            RateLimitBucket(
                "transaction-hour",
                transaction_dimension,
                5,
                3600,
            ),
        ],
    )
    await _verify_anti_bot(
        anti_bot,
        payload.anti_bot_token,
        action="verification_resend",
        remote_ip=context.remote_ip,
    )
    outcome = await service.resend(registration_token, context)
    _set_registration_cookie(response, outcome.registration_token)
    _harden_auth_response(response)
    await _enqueue_verification(email_sender, outcome)
    return ApiResponse(
        code=status.HTTP_202_ACCEPTED,
        message="如果注册事务仍然有效，我们已重新发送验证邮件",
        data=GENERIC_REGISTRATION_DATA,
    )


@router.post(
    "/email-verification/confirm",
    response_model=ApiResponse,
)
async def confirm_email_verification(
    payload: ConfirmEmailVerificationRequest,
    request: Request,
    response: Response,
    service: RegistrationService = Depends(get_registration_service),
) -> ApiResponse:
    """Activate an account by consuming one verification credential."""

    validate_json_origin(request)
    context = auth_request_context(request)
    registration_token = request.cookies.get(settings.AUTH_REGISTRATION_COOKIE_NAME)
    try:
        outcome = await service.confirm_email(
            payload,
            registration_token,
            context,
        )
    except RegistrationFlowError as exc:
        raise _api_error(exc) from exc

    response.delete_cookie(
        settings.AUTH_REGISTRATION_COOKIE_NAME,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    _harden_auth_response(response)
    return ApiResponse(
        message="邮箱验证成功",
        data={
            "user": {
                "id": str(outcome.user_id),
                "email": outcome.email,
                "display_name": outcome.display_name,
                "email_verified": True,
            },
            "authenticated": False,
        },
    )


async def _enqueue_verification(
    email_sender: EmailSender,
    outcome: RegistrationOutcome,
) -> None:
    delivery = outcome.delivery
    if delivery is None:
        return
    verification_url = (
        f"{settings.AUTH_FRONTEND_BASE_URL}/verify-email"
        f"?token={quote(delivery.link_token, safe='')}"
    )
    try:
        await email_sender.enqueue(
            AuthEmail(
                template_id="verify-email",
                recipient=delivery.recipient,
                variables={
                    "code": delivery.code,
                    "verification_url": verification_url,
                },
                idempotency_key=f"verify-email:{delivery.challenge_id}",
            )
        )
    except EmailDeliveryUnavailable:
        logger.error(
            "邮箱验证邮件入队失败",
            challenge_id=str(delivery.challenge_id),
        )
    except Exception as exc:
        logger.error(
            "邮箱验证邮件入队出现未预期错误",
            challenge_id=str(delivery.challenge_id),
            error_type=type(exc).__name__,
        )


async def _verify_anti_bot(
    verifier: AntiBotVerifier,
    token: str | None,
    *,
    action: str,
    remote_ip: str | None,
) -> None:
    try:
        decision = await verifier.verify(
            token,
            action=action,
            remote_ip=remote_ip,
        )
    except AntiBotUnavailable as exc:
        raise APIException(
            message="安全校验服务暂时不可用，请稍后重试",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="ANTI_BOT_UNAVAILABLE",
        ) from exc
    if not decision.allowed:
        raise APIException(
            message="安全校验未通过，请重试",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="ANTI_BOT_REJECTED",
        )


async def _enforce_rate_limits(
    limiter: AuthRateLimiter,
    action: str,
    buckets: list[RateLimitBucket],
) -> None:
    try:
        await limiter.enforce(action, buckets)
    except RateLimitExceeded as exc:
        raise APIException(
            message="请求过于频繁，请稍后再试",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="AUTH_RATE_LIMITED",
            headers={
                **AUTH_NO_STORE_HEADERS,
                "Retry-After": str(exc.retry_after),
            },
        ) from exc


def _set_registration_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.AUTH_REGISTRATION_COOKIE_NAME,
        token,
        max_age=settings.AUTH_REGISTRATION_TRANSACTION_MINUTES * 60,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def _clear_registration_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.AUTH_REGISTRATION_COOKIE_NAME,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def _set_session_cookie(response: Response, outcome: LoginOutcome) -> None:
    response.set_cookie(
        settings.AUTH_SESSION_COOKIE_NAME,
        outcome.session_token,
        max_age=outcome.cookie_max_age,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.AUTH_SESSION_COOKIE_NAME,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def _harden_auth_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _login_rate_limit_identifier(value: str) -> str:
    try:
        normalized, _ = normalize_email(value)
    except ValueError:
        return value.strip().casefold()[:320] or "invalid-email"
    return normalized


def _authenticated_data(user, profile, auth_session, csrf_token: str) -> dict:
    return {
        "authenticated": True,
        "csrf_token": csrf_token,
        "user": {
            "id": str(user.id),
            "email": user.email_display or user.email_normalized,
            "email_verified": user.email_verified_at is not None,
            "display_name": profile.display_name if profile else "",
            "locale": profile.locale if profile else "zh-CN",
            "timezone": profile.timezone if profile else "Asia/Shanghai",
        },
        "session": {
            "id": str(auth_session.id),
            "auth_method": auth_session.auth_method,
            "device_label": auth_session.device_label,
            "created_at": _utc_iso(auth_session.created_at),
            "idle_expires_at": _utc_iso(auth_session.idle_expires_at),
            "absolute_expires_at": _utc_iso(auth_session.absolute_expires_at),
        },
    }


def _utc_iso(value: datetime) -> str:
    return f"{value.isoformat(timespec='microseconds')}Z"


def _api_error(exc: RegistrationFlowError) -> APIException:
    return APIException(
        message=str(exc),
        status_code=exc.status_code,
        code=exc.code,
        headers=AUTH_NO_STORE_HEADERS,
    )
