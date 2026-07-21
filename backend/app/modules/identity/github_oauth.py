"""GitHub OAuth transactions, provider exchange, and account resolution."""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional
from urllib.parse import urlencode, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.types import new_uuid7
from app.modules.identity.context import AuthRequestContext
from app.modules.identity.models import (
    AuthActionToken,
    AuthEvent,
    AuthIdentity,
    User,
    UserConsent,
    UserProfile,
    utc_now,
)
from app.modules.identity.schemas import (
    GitHubOAuthLinkStartRequest,
    GitHubOAuthStartRequest,
)
from app.modules.identity.security import (
    action_token_digest,
    generate_opaque_token,
    identifier_digest,
    normalize_email,
    pack_ip_address,
    sanitize_user_agent,
)
from app.modules.identity.session import (
    AuthenticatedSession,
    LoginOutcome,
    SessionService,
)

GITHUB_PROVIDER = "github"
GITHUB_OAUTH_PURPOSE = "github_oauth"
GITHUB_STATE_DIGEST_PURPOSE = "github_oauth_state"
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"

ALLOWED_RETURN_PATHS = (
    "/today",
    "/agent",
    "/map",
    "/practice",
    "/mistakes",
    "/sources",
    "/states",
    "/account",
)


class GitHubOAuthFlowError(ValueError):
    """A user-safe GitHub OAuth failure with a trusted redirect target."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        return_path: str = "/login",
        redirect_path: str = "/login",
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.return_path = return_path
        self.redirect_path = redirect_path
        super().__init__(message)


class GitHubProviderError(RuntimeError):
    """GitHub rejected or failed an OAuth provider request."""


@dataclass(frozen=True)
class GitHubProfile:
    """Bounded GitHub identity fields used by the account domain."""

    subject: str
    username: Optional[str]
    display_name: str
    verified_email: Optional[str]


@dataclass(frozen=True)
class GitHubOAuthStartOutcome:
    """Authorization URL returned after persisting an OAuth transaction."""

    authorization_url: str
    expires_at: datetime
    verifier_cookie: str


@dataclass(frozen=True)
class GitHubOAuthCallbackOutcome:
    """Successful GitHub login or account binding and its destination."""

    login: Optional[LoginOutcome]
    return_path: str
    new_user: bool
    linked: bool = False


@dataclass(frozen=True)
class GitHubIdentitySummary:
    """Redacted GitHub identity details safe for account settings."""

    linked: bool
    username: Optional[str] = None
    email: Optional[str] = None
    linked_at: Optional[datetime] = None


@dataclass(frozen=True)
class _OAuthTransaction:
    verifier: str
    return_path: str
    remember_me: bool
    accept_terms: bool
    accept_privacy: bool
    source: str
    user_id: Optional[uuid.UUID]
    session_id: Optional[uuid.UUID]


class GitHubOAuthClient:
    """Minimal GitHub OAuth and user API client."""

    def __init__(
        self,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        callback_url: Optional[str] = None,
        http_client_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
    ) -> None:
        self.client_id = (
            client_id if client_id is not None else settings.AUTH_GITHUB_CLIENT_ID
        )
        self.client_secret = (
            client_secret
            if client_secret is not None
            else settings.AUTH_GITHUB_CLIENT_SECRET
        )
        self.callback_url = (
            callback_url
            if callback_url is not None
            else settings.AUTH_GITHUB_CALLBACK_URL
        )
        self.http_client_factory = http_client_factory or self._default_http_client

    def ensure_configured(self) -> None:
        if not self.client_id or not self.client_secret or not self.callback_url:
            raise GitHubProviderError("GitHub OAuth is not configured")

    def authorization_url(self, state: str, code_challenge: str) -> str:
        self.ensure_configured()
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.callback_url,
                "scope": "user:email",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{GITHUB_AUTHORIZE_URL}?{query}"

    async def exchange_profile(self, code: str, code_verifier: str) -> GitHubProfile:
        self.ensure_configured()
        try:
            async with self.http_client_factory() as client:
                token_response = await client.post(
                    GITHUB_TOKEN_URL,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "redirect_uri": self.callback_url,
                        "code_verifier": code_verifier,
                    },
                    headers={"Accept": "application/json"},
                )
                token_response.raise_for_status()
                access_token = _required_access_token(token_response.json())

                headers = {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": GITHUB_API_VERSION,
                }
                user_response = await client.get(
                    f"{GITHUB_API_URL}/user", headers=headers
                )
                user_response.raise_for_status()
                user_data = user_response.json()

                emails_response = await client.get(
                    f"{GITHUB_API_URL}/user/emails",
                    headers=headers,
                )
                emails_response.raise_for_status()
                emails_data = emails_response.json()
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise GitHubProviderError("GitHub OAuth provider request failed") from exc

        return _github_profile(user_data, emails_data)

    @staticmethod
    def _default_http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
        )


class GitHubOAuthService:
    """Execute one-time OAuth transactions without auto-merging accounts."""

    def __init__(
        self,
        db: AsyncSession,
        provider: GitHubOAuthClient,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.db = db
        self.provider = provider
        self.clock = clock

    async def start(
        self,
        payload: GitHubOAuthStartRequest,
        context: AuthRequestContext,
    ) -> GitHubOAuthStartOutcome:
        """Persist state and bind PKCE material to a short-lived browser Cookie."""

        try:
            self.provider.ensure_configured()
        except GitHubProviderError as exc:
            raise GitHubOAuthFlowError(
                "GITHUB_OAUTH_UNAVAILABLE",
                "GitHub 登录暂时不可用",
                status_code=503,
            ) from exc

        now = self.clock()
        state = generate_opaque_token()
        verifier = _generate_pkce_verifier()
        return_path = validate_return_path(
            payload.return_path,
            default="/today",
        )
        expires_at = now + timedelta(minutes=settings.AUTH_GITHUB_TRANSACTION_MINUTES)
        metadata = {
            "verifier_hash": action_token_digest(
                verifier,
                GITHUB_STATE_DIGEST_PURPOSE,
            ).hex(),
            "return_path": return_path,
            "remember_me": payload.remember_me,
            "accept_terms": payload.accept_terms,
            "accept_privacy": payload.accept_privacy,
            "source": payload.source,
        }
        self.db.add(
            AuthActionToken(
                id=new_uuid7(),
                purpose=GITHUB_OAUTH_PURPOSE,
                challenge_id=new_uuid7(),
                token_kind="state",
                token_hash=action_token_digest(
                    state,
                    GITHUB_STATE_DIGEST_PURPOSE,
                ),
                key_version=settings.AUTH_ACTION_TOKEN_KEY_VERSION,
                request_ip=pack_ip_address(context.remote_ip),
                metadata_json=metadata,
                created_at=now,
                expires_at=expires_at,
            )
        )
        await self.db.commit()
        return GitHubOAuthStartOutcome(
            authorization_url=self.provider.authorization_url(
                state,
                _pkce_challenge(verifier),
            ),
            expires_at=expires_at,
            verifier_cookie=verifier,
        )

    async def start_link(
        self,
        payload: GitHubOAuthLinkStartRequest,
        current: AuthenticatedSession,
        context: AuthRequestContext,
    ) -> GitHubOAuthStartOutcome:
        """Bind one OAuth transaction to the current user and session."""

        try:
            self.provider.ensure_configured()
        except GitHubProviderError as exc:
            raise GitHubOAuthFlowError(
                "GITHUB_OAUTH_UNAVAILABLE",
                "GitHub 绑定暂时不可用",
                status_code=503,
                return_path="/account",
                redirect_path="/account",
            ) from exc

        now = self.clock()
        state = generate_opaque_token()
        verifier = _generate_pkce_verifier()
        return_path = validate_return_path(
            payload.return_path,
            default="/account",
        )
        expires_at = now + timedelta(minutes=settings.AUTH_GITHUB_TRANSACTION_MINUTES)
        metadata = {
            "verifier_hash": action_token_digest(
                verifier,
                GITHUB_STATE_DIGEST_PURPOSE,
            ).hex(),
            "return_path": return_path,
            "remember_me": False,
            "accept_terms": False,
            "accept_privacy": False,
            "source": "link",
            "session_id": str(current.session.id),
        }
        self.db.add(
            AuthActionToken(
                id=new_uuid7(),
                user_id=current.user.id,
                purpose=GITHUB_OAUTH_PURPOSE,
                challenge_id=new_uuid7(),
                token_kind="state",
                token_hash=action_token_digest(
                    state,
                    GITHUB_STATE_DIGEST_PURPOSE,
                ),
                key_version=settings.AUTH_ACTION_TOKEN_KEY_VERSION,
                request_ip=pack_ip_address(context.remote_ip),
                metadata_json=metadata,
                created_at=now,
                expires_at=expires_at,
            )
        )
        await self.db.commit()
        return GitHubOAuthStartOutcome(
            authorization_url=self.provider.authorization_url(
                state,
                _pkce_challenge(verifier),
            ),
            expires_at=expires_at,
            verifier_cookie=verifier,
        )

    async def get_linked_identity(
        self,
        user_id: uuid.UUID,
    ) -> GitHubIdentitySummary:
        """Return the current account's GitHub binding without provider secrets."""

        identity = await self.db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.user_id == user_id,
                AuthIdentity.provider == GITHUB_PROVIDER,
            )
        )
        if identity is None:
            return GitHubIdentitySummary(linked=False)
        return GitHubIdentitySummary(
            linked=True,
            username=identity.provider_username,
            email=identity.provider_email,
            linked_at=identity.linked_at,
        )

    async def callback(
        self,
        *,
        state: Optional[str],
        code: Optional[str],
        provider_error: Optional[str],
        verifier_cookie: Optional[str],
        context: AuthRequestContext,
        previous_session_token: Optional[str],
    ) -> GitHubOAuthCallbackOutcome:
        """Consume state, resolve the stable GitHub identity, and create a session."""

        transaction = await self._consume_transaction(state, verifier_cookie)
        if provider_error or not code or len(code) > 1024:
            raise GitHubOAuthFlowError(
                "GITHUB_OAUTH_CANCELLED",
                "GitHub 授权未完成",
                status_code=400,
                return_path=transaction.return_path,
                redirect_path=_transaction_redirect_path(transaction),
            )

        try:
            profile = await self.provider.exchange_profile(code, transaction.verifier)
        except GitHubProviderError as exc:
            await self._record_failure(
                "provider_unavailable",
                context,
            )
            raise GitHubOAuthFlowError(
                "GITHUB_OAUTH_UNAVAILABLE",
                "GitHub 登录暂时不可用",
                status_code=503,
                return_path=transaction.return_path,
                redirect_path=_transaction_redirect_path(transaction),
            ) from exc

        if transaction.source == "link":
            return await self._link_identity(
                profile,
                transaction,
                context,
                previous_session_token,
            )
        return await self._resolve_account(
            profile,
            transaction,
            context,
            previous_session_token,
        )

    async def _consume_transaction(
        self,
        raw_state: Optional[str],
        raw_verifier: Optional[str],
    ) -> _OAuthTransaction:
        if (
            not raw_state
            or not 20 <= len(raw_state) <= 256
            or not raw_verifier
            or not 43 <= len(raw_verifier) <= 256
        ):
            raise _invalid_state_error()

        now = self.clock()
        token = await self.db.scalar(
            select(AuthActionToken)
            .where(
                AuthActionToken.purpose == GITHUB_OAUTH_PURPOSE,
                AuthActionToken.token_kind == "state",
                AuthActionToken.token_hash
                == action_token_digest(raw_state, GITHUB_STATE_DIGEST_PURPOSE),
            )
            .with_for_update()
        )
        if (
            token is None
            or token.consumed_at is not None
            or token.invalidated_at is not None
            or token.expires_at <= now
        ):
            await self.db.rollback()
            raise _invalid_state_error()

        try:
            transaction = _transaction_from_metadata(
                token.metadata_json,
                raw_verifier,
                token.user_id,
            )
        except (KeyError, TypeError, ValueError):
            token.invalidated_at = now
            await self.db.commit()
            raise _invalid_state_error()

        token.consumed_at = now
        await self.db.commit()
        return transaction

    async def _resolve_account(
        self,
        profile: GitHubProfile,
        transaction: _OAuthTransaction,
        context: AuthRequestContext,
        previous_session_token: Optional[str],
    ) -> GitHubOAuthCallbackOutcome:
        now = self.clock()
        identity = await self.db.scalar(
            select(AuthIdentity)
            .options(selectinload(AuthIdentity.user))
            .where(
                AuthIdentity.provider == GITHUB_PROVIDER,
                AuthIdentity.provider_subject == profile.subject,
            )
            .with_for_update()
        )
        new_user = False
        if identity is not None:
            user = identity.user
            identity.provider_username = profile.username
            identity.provider_email = profile.verified_email
            identity.provider_email_verified = profile.verified_email is not None
            identity.last_login_at = now
            identity.updated_at = now
        else:
            user = await self._create_user_for_profile(
                profile,
                transaction,
                context,
                now,
            )
            new_user = True

        session_service = SessionService(self.db, clock=self.clock)
        login = await session_service.create_for_external_login(
            user.id,
            auth_method=GITHUB_PROVIDER,
            context=context,
            previous_session_token=previous_session_token,
            remember_me=transaction.remember_me,
        )
        if login is None:
            await self._record_failure(
                "account_login_unavailable",
                context,
                user_id=user.id,
            )
            raise GitHubOAuthFlowError(
                "ACCOUNT_LOGIN_UNAVAILABLE",
                "账号当前无法登录，请联系支持",
                status_code=403,
                return_path=transaction.return_path,
            )

        return GitHubOAuthCallbackOutcome(
            login=login,
            return_path=transaction.return_path,
            new_user=new_user,
        )

    async def _link_identity(
        self,
        profile: GitHubProfile,
        transaction: _OAuthTransaction,
        context: AuthRequestContext,
        session_token: Optional[str],
    ) -> GitHubOAuthCallbackOutcome:
        if transaction.user_id is None or transaction.session_id is None:
            raise _invalid_state_error()

        current = await SessionService(self.db, clock=self.clock).authenticate(
            session_token,
            context,
        )
        if (
            current is None
            or current.user.id != transaction.user_id
            or current.session.id != transaction.session_id
        ):
            raise GitHubOAuthFlowError(
                "GITHUB_LINK_AUTH_REQUIRED",
                "登录状态已变化，请重新登录后绑定 GitHub",
                status_code=401,
                return_path=transaction.return_path,
                redirect_path="/account",
            )

        now = self.clock()
        identity = await self.db.scalar(
            select(AuthIdentity)
            .where(
                AuthIdentity.provider == GITHUB_PROVIDER,
                AuthIdentity.provider_subject == profile.subject,
            )
            .with_for_update()
        )
        if identity is not None:
            if identity.user_id != current.user.id:
                await self._record_failure(
                    "identity_owned_by_another_user",
                    context,
                    user_id=current.user.id,
                )
                raise GitHubOAuthFlowError(
                    "GITHUB_IDENTITY_IN_USE",
                    "该 GitHub 账号已绑定其他学习账户",
                    status_code=409,
                    return_path=transaction.return_path,
                    redirect_path="/account",
                )
            identity.provider_username = profile.username
            identity.provider_email = profile.verified_email
            identity.provider_email_verified = profile.verified_email is not None
            identity.updated_at = now
            await self.db.commit()
            return GitHubOAuthCallbackOutcome(
                login=None,
                return_path=transaction.return_path,
                new_user=False,
                linked=True,
            )

        existing_for_user = await self.db.scalar(
            select(AuthIdentity)
            .where(
                AuthIdentity.user_id == current.user.id,
                AuthIdentity.provider == GITHUB_PROVIDER,
            )
            .with_for_update()
        )
        if existing_for_user is not None:
            await self.db.rollback()
            raise GitHubOAuthFlowError(
                "GITHUB_ALREADY_LINKED",
                "当前账户已经绑定 GitHub",
                status_code=409,
                return_path=transaction.return_path,
                redirect_path="/account",
            )

        self.db.add(
            AuthIdentity(
                id=new_uuid7(),
                user_id=current.user.id,
                provider=GITHUB_PROVIDER,
                provider_subject=profile.subject,
                provider_username=profile.username,
                provider_email=profile.verified_email,
                provider_email_verified=profile.verified_email is not None,
                linked_at=now,
                updated_at=now,
            )
        )
        self.db.add(
            AuthEvent(
                user_id=current.user.id,
                session_id=current.session.id,
                event_type="identity_link",
                outcome="success",
                provider=GITHUB_PROVIDER,
                reason_code="account_settings",
                ip_address=pack_ip_address(context.remote_ip),
                user_agent=sanitize_user_agent(context.user_agent),
                request_id=(context.request_id or "")[:64] or None,
            )
        )
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise GitHubOAuthFlowError(
                "GITHUB_IDENTITY_IN_USE",
                "该 GitHub 账号已绑定其他学习账户",
                status_code=409,
                return_path=transaction.return_path,
                redirect_path="/account",
            ) from exc
        return GitHubOAuthCallbackOutcome(
            login=None,
            return_path=transaction.return_path,
            new_user=False,
            linked=True,
        )

    async def _create_user_for_profile(
        self,
        profile: GitHubProfile,
        transaction: _OAuthTransaction,
        context: AuthRequestContext,
        now: datetime,
    ) -> User:
        if not profile.verified_email:
            await self._record_failure("verified_email_required", context)
            raise GitHubOAuthFlowError(
                "GITHUB_EMAIL_REQUIRED",
                "请补充并验证邮箱后继续",
                status_code=409,
                return_path=transaction.return_path,
            )
        if not transaction.accept_terms or not transaction.accept_privacy:
            await self._record_failure("consent_required", context)
            raise GitHubOAuthFlowError(
                "GITHUB_CONSENT_REQUIRED",
                "创建账号前需要同意服务条款和隐私说明",
                status_code=409,
                return_path=transaction.return_path,
            )

        try:
            normalized_email, display_email = normalize_email(profile.verified_email)
        except ValueError as exc:
            await self._record_failure("verified_email_invalid", context)
            raise GitHubOAuthFlowError(
                "GITHUB_EMAIL_REQUIRED",
                "请补充并验证邮箱后继续",
                status_code=409,
                return_path=transaction.return_path,
            ) from exc

        existing_user = await self.db.scalar(
            select(User)
            .where(User.email_normalized == normalized_email)
            .with_for_update()
        )
        if existing_user is not None:
            await self._record_failure(
                "existing_email_requires_link",
                context,
                user_id=existing_user.id,
                identifier=normalized_email,
            )
            raise GitHubOAuthFlowError(
                "GITHUB_ACCOUNT_LINK_REQUIRED",
                "该邮箱已有账号，请先验证现有账号后再绑定 GitHub",
                status_code=409,
                return_path=transaction.return_path,
            )

        user_id = new_uuid7()
        user = User(
            id=user_id,
            email_normalized=normalized_email,
            email_display=display_email,
            email_verified_at=now,
            status="active",
            activated_at=now,
            created_at=now,
            updated_at=now,
        )
        user.profile = UserProfile(
            user_id=user_id,
            display_name=_bounded_display_name(profile),
            created_at=now,
            updated_at=now,
        )
        user.identities.append(
            AuthIdentity(
                id=new_uuid7(),
                user_id=user_id,
                provider=GITHUB_PROVIDER,
                provider_subject=profile.subject,
                provider_username=profile.username,
                provider_email=display_email,
                provider_email_verified=True,
                linked_at=now,
                last_login_at=now,
                updated_at=now,
            )
        )
        self.db.add(user)
        self.db.add_all(
            [
                UserConsent(
                    user_id=user_id,
                    document_type="terms",
                    document_version=settings.AUTH_TERMS_VERSION,
                    accepted_at=now,
                    ip_address=pack_ip_address(context.remote_ip),
                    source="github_oauth",
                ),
                UserConsent(
                    user_id=user_id,
                    document_type="privacy",
                    document_version=settings.AUTH_PRIVACY_VERSION,
                    accepted_at=now,
                    ip_address=pack_ip_address(context.remote_ip),
                    source="github_oauth",
                ),
            ]
        )
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise GitHubOAuthFlowError(
                "GITHUB_ACCOUNT_LINK_REQUIRED",
                "该账号需要先验证现有账户后再绑定 GitHub",
                status_code=409,
                return_path=transaction.return_path,
            ) from exc
        return user

    async def _record_failure(
        self,
        reason_code: str,
        context: AuthRequestContext,
        *,
        user_id: Optional[uuid.UUID] = None,
        identifier: Optional[str] = None,
    ) -> None:
        self.db.add(
            AuthEvent(
                user_id=user_id,
                session_id=None,
                event_type="oauth_login",
                outcome="failure",
                provider=GITHUB_PROVIDER,
                reason_code=reason_code,
                identifier_hmac=(identifier_digest(identifier) if identifier else None),
                ip_address=pack_ip_address(context.remote_ip),
                user_agent=sanitize_user_agent(context.user_agent),
                request_id=(context.request_id or "")[:64] or None,
            )
        )
        await self.db.commit()


def validate_return_path(value: Optional[str], *, default: str) -> str:
    """Accept only known frontend routes and relative query strings."""

    candidate = (value or "").strip()
    if not candidate:
        return default
    parsed = urlsplit(candidate)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or "\\" in candidate
        or candidate.startswith("//")
    ):
        return default
    if not any(
        parsed.path == allowed or parsed.path.startswith(f"{allowed}/")
        for allowed in ALLOWED_RETURN_PATHS
    ):
        return default
    return candidate


def _generate_pkce_verifier() -> str:
    return generate_opaque_token() + generate_opaque_token()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _transaction_redirect_path(transaction: _OAuthTransaction) -> str:
    return "/account" if transaction.source == "link" else "/login"


def _transaction_from_metadata(
    metadata: Optional[dict],
    raw_verifier: str,
    user_id: Optional[uuid.UUID],
) -> _OAuthTransaction:
    if not isinstance(metadata, dict):
        raise TypeError("missing OAuth metadata")
    verifier_hash = str(metadata["verifier_hash"])
    presented_hash = action_token_digest(
        raw_verifier,
        GITHUB_STATE_DIGEST_PURPOSE,
    ).hex()
    if not hmac.compare_digest(verifier_hash, presented_hash):
        raise ValueError("invalid PKCE verifier")
    return_path = validate_return_path(
        str(metadata["return_path"]),
        default="/today",
    )
    source = str(metadata["source"])
    if source not in {"login", "register", "link"}:
        raise ValueError("invalid OAuth source")
    session_id = None
    if source == "link":
        if user_id is None:
            raise ValueError("missing OAuth link user")
        session_id = uuid.UUID(str(metadata["session_id"]))
    return _OAuthTransaction(
        verifier=raw_verifier,
        return_path=return_path,
        remember_me=metadata.get("remember_me") is True,
        accept_terms=metadata.get("accept_terms") is True,
        accept_privacy=metadata.get("accept_privacy") is True,
        source=source,
        user_id=user_id,
        session_id=session_id,
    )


def _required_access_token(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("invalid token response")
    token = payload.get("access_token")
    if not isinstance(token, str) or not token or len(token) > 2048:
        raise ValueError("missing access token")
    return token


def _github_profile(user_data: object, emails_data: object) -> GitHubProfile:
    if not isinstance(user_data, dict):
        raise GitHubProviderError("invalid GitHub user response")
    raw_id = user_data.get("id")
    if not isinstance(raw_id, int) or raw_id <= 0:
        raise GitHubProviderError("missing stable GitHub user id")

    username = _bounded_optional_text(user_data.get("login"), 191)
    display_name = _bounded_optional_text(user_data.get("name"), 64)
    verified_email = _select_verified_email(emails_data)
    return GitHubProfile(
        subject=str(raw_id),
        username=username,
        display_name=display_name or username or "GitHub 学习者",
        verified_email=verified_email,
    )


def _select_verified_email(payload: object) -> Optional[str]:
    if not isinstance(payload, list):
        raise GitHubProviderError("invalid GitHub email response")
    candidates = [
        item
        for item in payload
        if isinstance(item, dict)
        and item.get("verified") is True
        and isinstance(item.get("email"), str)
    ]
    primary = next((item for item in candidates if item.get("primary") is True), None)
    selected = primary or (candidates[0] if candidates else None)
    if selected is None:
        return None
    email = str(selected["email"]).strip()
    return email[:320] or None


def _bounded_optional_text(value: object, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    return normalized[:limit] or None


def _bounded_display_name(profile: GitHubProfile) -> str:
    return _bounded_optional_text(profile.display_name, 64) or "GitHub 学习者"


def _invalid_state_error() -> GitHubOAuthFlowError:
    return GitHubOAuthFlowError(
        "GITHUB_OAUTH_STATE_INVALID",
        "GitHub 登录请求已失效，请重新发起",
        status_code=400,
    )
