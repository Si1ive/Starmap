"""Public learning-user registration and email-verification endpoints."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.core.config import settings
from app.core.logging import get_logger, get_request_id
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
from app.modules.identity.rate_limit import (
    AuthRateLimiter,
    RateLimitBucket,
    RateLimitExceeded,
    get_auth_rate_limiter,
)
from app.modules.identity.registration import (
    AuthRequestContext,
    RegistrationFlowError,
    RegistrationOutcome,
    RegistrationService,
)
from app.modules.identity.schemas import (
    ConfirmEmailVerificationRequest,
    RegisterRequest,
    ResendEmailVerificationRequest,
)
from app.modules.identity.security import (
    PasswordService,
    get_password_service,
    normalize_email,
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

    context = _request_context(request)
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

    context = _request_context(request)
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

    context = _request_context(request)
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
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc


def _request_context(request: Request) -> AuthRequestContext:
    return AuthRequestContext(
        remote_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=get_request_id(),
    )


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


def _harden_auth_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _api_error(exc: RegistrationFlowError) -> APIException:
    return APIException(
        message=str(exc),
        status_code=exc.status_code,
        code=exc.code,
    )
