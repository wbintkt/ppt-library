"""全局配置"""
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings


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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
