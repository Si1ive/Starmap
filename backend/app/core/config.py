from pydantic_settings import BaseSettings
from typing import List
import os
from pathlib import Path

class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "408考研学习平台"
    ENV: str = os.getenv("ENV", "development")
    DEBUG: bool = ENV == "development"

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
