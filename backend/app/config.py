"""全局配置"""
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # 基础
    app_name: str = "PPT 素材智能检索系统"
    data_dir: Path = Path("/data/ppt-library")
    # 数据库
    database_url: str = "postgresql+psycopg2://ppt_user:PptLib%232026@127.0.0.1:5432/ppt_library"
    # Redis / Celery
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_backend_url: str = "redis://127.0.0.1:6379/1"
    # Embedding（阿里云百炼）
    dashscope_api_key: str = ""
    embed_model: str = "qwen3-vl-embedding"
    embed_dim: int = 512
    # 认证
    auth_username: str = "admin"
    auth_password: str = "PptLib2026"
    secret_key: str = secrets.token_hex(32)
    token_expire_minutes: int = 60 * 24 * 7  # 7 天
    # 上传
    max_upload_mb: int = 200
    # 检索
    search_top_k: int = 20
    rerank_enabled: bool = True
    rerank_model: str = "qwen3.7-text-rerank"
    rerank_candidate_limit: int = Field(default=60, ge=50, le=100)
    rerank_text_chars: int = Field(default=1800, ge=500, le=4000)
    rerank_timeout_seconds: float = Field(default=10, ge=1, le=60)
    search_intent_model: str = "qwen-flash"
    search_intent_timeout_seconds: float = Field(default=2.5, ge=0.1, le=5)
    search_model_api_base: str = "https://dashscope.aliyuncs.com"
    search_embedding_timeout_seconds: float = Field(default=5, ge=1, le=10)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
