"""Learning-user registration, login, and session endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
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
from app.modules.identity.password_reset import (
    PasswordResetFlowError,
    PasswordResetOutcome,
    PasswordResetRequestOutcome,
    PasswordResetService,
)
from app.modules.identity.github_oauth import (
    GitHubOAuthClient,
    GitHubOAuthFlowError,
    GitHubOAuthService,
)
from app.modules.identity.registration import (
    RegistrationFlowError,
    RegistrationOutcome,
    RegistrationService,
)
from app.modules.identity.schemas import (
    ConfirmEmailVerificationRequest,
    ForgotPasswordRequest,
    GitHubOAuthLinkStartRequest,
    GitHubOAuthStartRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    ResendEmailVerificationRequest,
)
from app.modules.identity.security import (
    PasswordService,
    get_password_service,
    identifier_digest,
    normalize_email,
    sanitize_user_agent,
)
from app.modules.identity.session import (
    AuthenticatedSession,
    LoginFlowError,
    LoginOutcome,
    LoginService,
    SessionManagementError,
    SessionService,
    SessionSummary,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["用户认证"])

GENERIC_REGISTRATION_DATA = {
    "verification_required": True,
    "resend_after_seconds": 60,
}
GENERIC_PASSWORD_RESET_DATA = {"accepted": True}


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


def get_password_reset_service(
    db: AsyncSession = Depends(get_db),
    password_service: PasswordService = Depends(get_password_service),
) -> PasswordResetService:
    """Build the request-scoped password-reset service."""

    return PasswordResetService(db, password_service)


def get_github_oauth_service(
    db: AsyncSession = Depends(get_db),
) -> GitHubOAuthService:
    """Build the request-scoped GitHub OAuth service."""

    return GitHubOAuthService(db, GitHubOAuthClient())


@router.post(
    "/github/start",
    response_model=ApiResponse,
)
async def start_github_oauth(
    payload: GitHubOAuthStartRequest,
    request: Request,
    response: Response,
    service: GitHubOAuthService = Depends(get_github_oauth_service),
    rate_limiter: AuthRateLimiter = Depends(get_auth_rate_limiter),
) -> ApiResponse:
    """Create one server-side OAuth transaction and return GitHub's URL."""

    validate_json_origin(request)
    context = auth_request_context(request)
    device_signal = (
        f"{context.remote_ip or 'unknown'}:"
        f"{sanitize_user_agent(context.user_agent) or 'unknown'}"
    )
    await _enforce_rate_limits(
        rate_limiter,
        "github-oauth-start",
        [
            RateLimitBucket("ip", context.remote_ip or "unknown", 30, 900),
            RateLimitBucket("device", device_signal, 20, 900),
        ],
    )
    try:
        outcome = await service.start(payload, context)
    except GitHubOAuthFlowError as exc:
        raise APIException(
            message=str(exc),
            status_code=exc.status_code,
            code=exc.code,
            headers=AUTH_NO_STORE_HEADERS,
        ) from exc

    _harden_auth_response(response)
    response.set_cookie(
        settings.AUTH_GITHUB_OAUTH_COOKIE_NAME,
        outcome.verifier_cookie,
        max_age=settings.AUTH_GITHUB_TRANSACTION_MINUTES * 60,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return ApiResponse(
        message="GitHub 授权已准备",
        data={
            "authorization_url": outcome.authorization_url,
            "expires_at": _utc_iso(outcome.expires_at),
        },
    )


@router.get(
    "/github/link",
    response_model=ApiResponse,
)
async def get_github_link(
    response: Response,
    current: AuthenticatedSession = Depends(require_current_session),
    service: GitHubOAuthService = Depends(get_github_oauth_service),
) -> ApiResponse:
    """Return the current account's GitHub binding status."""

    identity = await service.get_linked_identity(current.user.id)
    _harden_auth_response(response)
    return ApiResponse(
        data={
            "linked": identity.linked,
            "username": identity.username,
            "email": identity.email,
            "linked_at": (
                _utc_iso(identity.linked_at) if identity.linked_at is not None else None
            ),
        }
    )


@router.post(
    "/github/link/start",
    response_model=ApiResponse,
)
async def start_github_link(
    payload: GitHubOAuthLinkStartRequest,
    request: Request,
    response: Response,
    current: AuthenticatedSession = Depends(require_csrf_session),
    service: GitHubOAuthService = Depends(get_github_oauth_service),
    rate_limiter: AuthRateLimiter = Depends(get_auth_rate_limiter),
) -> ApiResponse:
    """Create a GitHub binding transaction for the current account."""

    context = auth_request_context(request)
    await _enforce_rate_limits(
        rate_limiter,
        "github-oauth-link-start",
        [
            RateLimitBucket("user", str(current.user.id), 10, 900),
            RateLimitBucket("ip", context.remote_ip or "unknown", 30, 900),
        ],
    )
    try:
        outcome = await service.start_link(payload, current, context)
    except GitHubOAuthFlowError as exc:
        raise APIException(
            message=str(exc),
            status_code=exc.status_code,
            code=exc.code,
            headers=AUTH_NO_STORE_HEADERS,
        ) from exc

    _harden_auth_response(response)
    response.set_cookie(
        settings.AUTH_GITHUB_OAUTH_COOKIE_NAME,
        outcome.verifier_cookie,
        max_age=settings.AUTH_GITHUB_TRANSACTION_MINUTES * 60,
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return ApiResponse(
        message="GitHub 绑定授权已准备",
        data={
            "authorization_url": outcome.authorization_url,
            "expires_at": _utc_iso(outcome.expires_at),
        },
    )


@router.get("/github/callback")
async def github_oauth_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    service: GitHubOAuthService = Depends(get_github_oauth_service),
) -> RedirectResponse:
    """Validate GitHub's callback, rotate the session, and redirect safely."""

    try:
        outcome = await service.callback(
            state=state,
            code=code,
            provider_error=error,
            verifier_cookie=request.cookies.get(settings.AUTH_GITHUB_OAUTH_COOKIE_NAME),
            context=auth_request_context(request),
            previous_session_token=request.cookies.get(
                settings.AUTH_SESSION_COOKIE_NAME
            ),
        )
    except GitHubOAuthFlowError as exc:
        redirect = RedirectResponse(
            _oauth_frontend_redirect(
                exc.redirect_path,
                oauth_error=exc.code,
                return_path=exc.return_path,
            ),
            status_code=status.HTTP_303_SEE_OTHER,
        )
        _clear_github_oauth_cookie(redirect)
        _harden_auth_response(redirect)
        return redirect

    if outcome.linked:
        redirect = RedirectResponse(
            _oauth_frontend_redirect(
                outcome.return_path,
                github="linked",
            ),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    else:
        redirect = RedirectResponse(
            _oauth_frontend_redirect(
                outcome.return_path,
                oauth="success",
                new_user="1" if outcome.new_user else "0",
            ),
            status_code=status.HTTP_303_SEE_OTHER,
        )
        if outcome.login is None:
            raise RuntimeError("GitHub login outcome is missing session data")
        _set_session_cookie(redirect, outcome.login)
        _clear_registration_cookie(redirect)
    _clear_github_oauth_cookie(redirect)
    _harden_auth_response(redirect)
    return redirect


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


@router.get(
    "/sessions",
    response_model=ApiResponse,
)
async def list_active_sessions(
    response: Response,
    current: AuthenticatedSession = Depends(require_current_session),
    service: SessionService = Depends(get_session_service),
) -> ApiResponse:
    """Return redacted active-session summaries for the current user."""

    sessions = await service.list_active_sessions(current)
    _harden_auth_response(response)
    return ApiResponse(
        data={
            "sessions": [_session_summary_data(item) for item in sessions],
        }
    )


@router.post(
    "/sessions/{session_id}/revoke",
    response_model=ApiResponse,
)
async def revoke_other_session(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    current: AuthenticatedSession = Depends(require_csrf_session),
    service: SessionService = Depends(get_session_service),
) -> ApiResponse:
    """Revoke one owned non-current session after CSRF validation."""

    try:
        await service.revoke_other_session(
            current,
            session_id,
            auth_request_context(request),
        )
    except SessionManagementError as exc:
        raise _session_management_api_error(exc) from exc

    _harden_auth_response(response)
    return ApiResponse(
        message="登录会话已撤销",
        data={
            "revoked": True,
            "session_id": str(session_id),
        },
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
    session_service: SessionService = Depends(get_session_service),
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

    session_outcome = None
    if outcome.same_browser:
        create_session = session_service.create_after_email_verification
        session_outcome = await create_session(
            outcome.user_id,
            context,
            request.cookies.get(settings.AUTH_SESSION_COOKIE_NAME),
        )

    _clear_registration_cookie(response)
    if session_outcome is not None:
        _set_session_cookie(response, session_outcome)
        data = _authenticated_data(
            session_outcome.user,
            session_outcome.profile,
            session_outcome.session,
            session_outcome.csrf_token,
        )
    else:
        data = {
            "user": {
                "id": str(outcome.user_id),
                "email": outcome.email,
                "display_name": outcome.display_name,
                "email_verified": True,
            },
            "authenticated": False,
        }
    _harden_auth_response(response)
    return ApiResponse(
        message="邮箱验证成功",
        data=data,
    )


@router.post(
    "/password/forgot",
    response_model=ApiResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    response: Response,
    service: PasswordResetService = Depends(get_password_reset_service),
    rate_limiter: AuthRateLimiter = Depends(get_auth_rate_limiter),
    anti_bot: AntiBotVerifier = Depends(get_anti_bot_verifier),
    email_sender: EmailSender = Depends(get_email_sender),
) -> ApiResponse:
    """Issue a reset email while keeping account existence private."""

    validate_json_origin(request)
    context = auth_request_context(request)
    identifier = _password_reset_rate_limit_identifier(payload.email)
    await _enforce_rate_limits(
        rate_limiter,
        "password-forgot",
        [
            RateLimitBucket("ip", context.remote_ip or "unknown", 10, 3600),
            RateLimitBucket("email", identifier, 3, 3600),
        ],
    )
    await _verify_anti_bot(
        anti_bot,
        payload.anti_bot_token,
        action="password_forgot",
        remote_ip=context.remote_ip,
    )
    outcome = await service.request_reset(payload, context)
    _harden_auth_response(response)
    await _enqueue_password_reset(email_sender, outcome)
    return ApiResponse(
        code=status.HTTP_202_ACCEPTED,
        message="如果账号存在，我们会发送密码重置邮件",
        data=GENERIC_PASSWORD_RESET_DATA,
    )


@router.post(
    "/password/reset",
    response_model=ApiResponse,
)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    response: Response,
    service: PasswordResetService = Depends(get_password_reset_service),
    rate_limiter: AuthRateLimiter = Depends(get_auth_rate_limiter),
    email_sender: EmailSender = Depends(get_email_sender),
) -> ApiResponse:
    """Consume one reset token without creating a new login session."""

    validate_json_origin(request)
    context = auth_request_context(request)
    token_dimension = identifier_digest(f"password-reset-token:{payload.token}").hex()
    await _enforce_rate_limits(
        rate_limiter,
        "password-reset",
        [
            RateLimitBucket("ip", context.remote_ip or "unknown", 20, 3600),
            RateLimitBucket("token", token_dimension, 5, 3600),
        ],
    )
    try:
        outcome = await service.reset_password(payload, context)
    except PasswordResetFlowError as exc:
        raise _password_reset_api_error(exc) from exc

    _clear_session_cookie(response)
    _harden_auth_response(response)
    await _enqueue_password_changed(email_sender, outcome)
    return ApiResponse(
        message="密码已重置，请重新登录",
        data={
            "password_reset": True,
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


async def _enqueue_password_reset(
    email_sender: EmailSender,
    outcome: PasswordResetRequestOutcome,
) -> None:
    delivery = outcome.delivery
    if delivery is None:
        return
    reset_url = (
        f"{settings.AUTH_FRONTEND_BASE_URL}/reset-password"
        f"?token={quote(delivery.token, safe='')}"
    )
    try:
        await email_sender.enqueue(
            AuthEmail(
                template_id="reset-password",
                recipient=delivery.recipient,
                variables={"reset_url": reset_url},
                idempotency_key=f"reset-password:{delivery.challenge_id}",
            )
        )
    except EmailDeliveryUnavailable:
        logger.error(
            "密码重置邮件入队失败",
            challenge_id=str(delivery.challenge_id),
        )
    except Exception as exc:
        logger.error(
            "密码重置邮件入队出现未预期错误",
            challenge_id=str(delivery.challenge_id),
            error_type=type(exc).__name__,
        )


async def _enqueue_password_changed(
    email_sender: EmailSender,
    outcome: PasswordResetOutcome,
) -> None:
    try:
        await email_sender.enqueue(
            AuthEmail(
                template_id="password-changed",
                recipient=outcome.recipient,
                variables={},
                idempotency_key=f"password-changed:{outcome.challenge_id}",
            )
        )
    except EmailDeliveryUnavailable:
        logger.error(
            "密码变更通知邮件入队失败",
            challenge_id=str(outcome.challenge_id),
        )
    except Exception as exc:
        logger.error(
            "密码变更通知邮件入队出现未预期错误",
            challenge_id=str(outcome.challenge_id),
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


def _clear_github_oauth_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.AUTH_GITHUB_OAUTH_COOKIE_NAME,
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


def _password_reset_rate_limit_identifier(value: str) -> str:
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


def _session_summary_data(summary: SessionSummary) -> dict:
    return {
        "id": str(summary.id),
        "auth_method": summary.auth_method,
        "device_label": summary.device_label,
        "created_at": _utc_iso(summary.created_at),
        "last_seen_at": _utc_iso(summary.last_seen_at),
        "idle_expires_at": _utc_iso(summary.idle_expires_at),
        "absolute_expires_at": _utc_iso(summary.absolute_expires_at),
        "is_current": summary.is_current,
        "location_label": summary.location_label,
    }


def _oauth_frontend_redirect(path: str, **values: str) -> str:
    """Append bounded OAuth status fields to one trusted frontend path."""

    parsed = urlsplit(path)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(values)
    relative = urlunsplit(("", "", parsed.path, urlencode(query), ""))
    return f"{settings.AUTH_FRONTEND_BASE_URL}{relative}"


def _utc_iso(value: datetime) -> str:
    return f"{value.isoformat(timespec='microseconds')}Z"


def _api_error(exc: RegistrationFlowError) -> APIException:
    return APIException(
        message=str(exc),
        status_code=exc.status_code,
        code=exc.code,
        headers=AUTH_NO_STORE_HEADERS,
    )


def _password_reset_api_error(exc: PasswordResetFlowError) -> APIException:
    return APIException(
        message=str(exc),
        status_code=exc.status_code,
        code=exc.code,
        headers=AUTH_NO_STORE_HEADERS,
    )


def _session_management_api_error(exc: SessionManagementError) -> APIException:
    return APIException(
        message=str(exc),
        status_code=exc.status_code,
        code=exc.code,
        headers=AUTH_NO_STORE_HEADERS,
    )
