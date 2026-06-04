from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "StarMap"
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
    
    # Neo4j
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "starmap123")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    # ChromaDB
    CHROMA_HOST: str = os.getenv("CHROMA_HOST", "localhost")
    CHROMA_PORT: int = int(os.getenv("CHROMA_PORT", "8001"))
    
    # MySQL
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "starmap")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "starmap123")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "starmap")
    
    # 日志
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    model_config = {
        "env_file": ".env"
    }

settings = Settings()
