from pydantic_settings import BaseSettings
from typing import List
import os
from pathlib import Path

class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "408考研学习平台"
    ENV: str = os.getenv("ENV", "development")
    DEBUG: bool = ENV == "development"

    # Admin authentication
    ADMIN_JWT_SECRET: str = os.getenv(
        "ADMIN_JWT_SECRET",
        "development-only-admin-jwt-secret-change-me",
    )
    ADMIN_JWT_ALGORITHM: str = os.getenv("ADMIN_JWT_ALGORITHM", "HS256")
    ADMIN_JWT_EXPIRE_MINUTES: int = int(
        os.getenv("ADMIN_JWT_EXPIRE_MINUTES", "480")
    )
    ADMIN_JWT_ISSUER: str = os.getenv("ADMIN_JWT_ISSUER", "starmap-admin")
    ADMIN_JWT_AUDIENCE: str = os.getenv("ADMIN_JWT_AUDIENCE", "starmap-admin")

    # Learning-user authentication
    AUTH_ACTION_TOKEN_SECRET: str = os.getenv(
        "AUTH_ACTION_TOKEN_SECRET",
        "development-only-action-token-secret-change-me",
    )
    AUTH_CSRF_SECRET: str = os.getenv(
        "AUTH_CSRF_SECRET",
        "development-only-csrf-secret-change-me",
    )
    AUTH_IDENTIFIER_HMAC_SECRET: str = os.getenv(
        "AUTH_IDENTIFIER_HMAC_SECRET",
        "development-only-identifier-secret-change-me",
    )
    AUTH_ACTION_TOKEN_KEY_VERSION: int = int(
        os.getenv("AUTH_ACTION_TOKEN_KEY_VERSION", "1")
    )
    AUTH_SESSION_COOKIE_NAME: str = os.getenv(
        "AUTH_SESSION_COOKIE_NAME",
        "__Host-starmap_session" if ENV == "production" else "starmap_session",
    )
    AUTH_REGISTRATION_COOKIE_NAME: str = os.getenv(
        "AUTH_REGISTRATION_COOKIE_NAME",
        (
            "__Host-starmap_registration"
            if ENV == "production"
            else "starmap_registration"
        ),
    )
    AUTH_GITHUB_OAUTH_COOKIE_NAME: str = os.getenv(
        "AUTH_GITHUB_OAUTH_COOKIE_NAME",
        (
            "__Host-starmap_github_oauth"
            if ENV == "production"
            else "starmap_github_oauth"
        ),
    )
    AUTH_COOKIE_SECURE: bool = (
        os.getenv(
            "AUTH_COOKIE_SECURE",
            "true" if ENV == "production" else "false",
        ).lower()
        == "true"
    )
    AUTH_SESSION_IDLE_HOURS: int = int(
        os.getenv("AUTH_SESSION_IDLE_HOURS", "12")
    )
    AUTH_SESSION_ABSOLUTE_DAYS: int = int(
        os.getenv("AUTH_SESSION_ABSOLUTE_DAYS", "7")
    )
    AUTH_REMEMBER_IDLE_DAYS: int = int(
        os.getenv("AUTH_REMEMBER_IDLE_DAYS", "7")
    )
    AUTH_REMEMBER_ABSOLUTE_DAYS: int = int(
        os.getenv("AUTH_REMEMBER_ABSOLUTE_DAYS", "30")
    )
    AUTH_SESSION_TOUCH_MINUTES: int = int(
        os.getenv("AUTH_SESSION_TOUCH_MINUTES", "5")
    )
    AUTH_EMAIL_VERIFY_LINK_MINUTES: int = int(
        os.getenv("AUTH_EMAIL_VERIFY_LINK_MINUTES", "30")
    )
    AUTH_EMAIL_VERIFY_CODE_MINUTES: int = int(
        os.getenv("AUTH_EMAIL_VERIFY_CODE_MINUTES", "10")
    )
    AUTH_REGISTRATION_TRANSACTION_MINUTES: int = int(
        os.getenv("AUTH_REGISTRATION_TRANSACTION_MINUTES", "30")
    )
    AUTH_EMAIL_VERIFY_MAX_ATTEMPTS: int = int(
        os.getenv("AUTH_EMAIL_VERIFY_MAX_ATTEMPTS", "5")
    )
    AUTH_PASSWORD_RESET_MINUTES: int = int(
        os.getenv("AUTH_PASSWORD_RESET_MINUTES", "30")
    )
    AUTH_TERMS_VERSION: str = os.getenv("AUTH_TERMS_VERSION", "2026-07-16")
    AUTH_PRIVACY_VERSION: str = os.getenv(
        "AUTH_PRIVACY_VERSION",
        "2026-07-16",
    )
    AUTH_FRONTEND_BASE_URL: str = os.getenv(
        "AUTH_FRONTEND_BASE_URL",
        "http://localhost:5173",
    ).rstrip("/")
    AUTH_GITHUB_CLIENT_ID: str = os.getenv("AUTH_GITHUB_CLIENT_ID", "")
    AUTH_GITHUB_CLIENT_SECRET: str = os.getenv("AUTH_GITHUB_CLIENT_SECRET", "")
    AUTH_GITHUB_CALLBACK_URL: str = os.getenv(
        "AUTH_GITHUB_CALLBACK_URL",
        "http://localhost:8000/api/v1/auth/github/callback",
    )
    AUTH_GITHUB_TRANSACTION_MINUTES: int = int(
        os.getenv("AUTH_GITHUB_TRANSACTION_MINUTES", "10")
    )
    AUTH_EMAIL_BACKEND: str = os.getenv("AUTH_EMAIL_BACKEND", "memory")
    AUTH_ANTI_BOT_MODE: str = os.getenv("AUTH_ANTI_BOT_MODE", "disabled")

    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000"
    ]

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4")

    # GitHub
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")

    # Qdrant
    QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))

    # MySQL
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "starmap")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "starmap123")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "starmap")

    # 日志
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # PDF Parser Service
    PDF_PARSER_LOCAL_ENDPOINT: str = os.getenv("PDF_PARSER_LOCAL_ENDPOINT", "http://localhost:8090")

    # Corpus uploads
    CORPUS_UPLOAD_DIR: str = os.getenv(
        "CORPUS_UPLOAD_DIR",
        str(Path(__file__).resolve().parents[2] / "uploads"),
    )
    CORPUS_UPLOAD_MAX_BYTES: int = int(
        os.getenv("CORPUS_UPLOAD_MAX_BYTES", str(200 * 1024 * 1024))
    )
    
    model_config = {
        "env_file": ".env"
    }

settings = Settings()
