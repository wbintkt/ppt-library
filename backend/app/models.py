"""ORM 模型"""
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, BigInteger, Index, UniqueConstraint, ForeignKey,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import relationship

from .database import Base


class AppSetting(Base):
    """运行时配置（key-value，如 DASHSCOPE_API_KEY）"""
    __tablename__ = "app_settings"

    key = Column(String(128), primary_key=True)
    value = Column(Text, default="")
    update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PPTFile(Base):
    """PPT 原文件记录"""
    __tablename__ = "ppt_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(512), nullable=False)          # 原始文件名（含扩展名）
    stored_name = Column(String(256), nullable=False)   # 存储文件名 ppt_{id}.pptx
    file_path = Column(String(1024), nullable=False)    # 绝对路径
    category = Column(String(128), default="未分类")     # 分类
    tags = Column(String(512), default="")              # 标签（逗号分隔）
    source = Column(String(256), default="")            # 来源
    file_size = Column(BigInteger, default=0)
    file_hash = Column(String(64), default="")          # SHA-256
    page_count = Column(Integer, default=0)
    status = Column(String(32), default="parsing")      # parsing/embedding/ready/ready_limited/failed
    error_message = Column(Text, default="")
    progress = Column(Integer, default=0)               # 0-100
    upload_time = Column(DateTime, default=datetime.utcnow)
    update_time = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pages = relationship("PPTPage", back_populates="file", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_ppt_files_category", "category"),
        Index("ix_ppt_files_status", "status"),
    )


class PPTPage(Base):
    """PPT 页面记录（一页一条，含 PNG + 向量）"""
    __tablename__ = "ppt_pages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("ppt_files.id", ondelete="CASCADE"), nullable=False)
    page_no = Column(Integer, nullable=False)           # 页码（1 起）
    title = Column(String(512), default="")             # 页面标题（自动提取）
    text = Column(Text, default="")                     # 页面提取文本
    png_path = Column(String(1024), default="")         # PNG 绝对路径
    image_hash = Column(String(64), default="")         # PNG SHA-256
    tags = Column(String(512), default="")              # 页面标签
    embedding_status = Column(String(32), default="pending")  # pending/done/failed
    embedding = Column(Vector(512), nullable=True)      # qwen3-vl-embedding 512 维
    text_tsv = Column(TSVECTOR, nullable=True)          # 全文检索（降级/混合检索用）
    created_at = Column(DateTime, default=datetime.utcnow)

    file = relationship("PPTFile", back_populates="pages")

    __table_args__ = (
        UniqueConstraint("file_id", "page_no", name="uq_file_page"),
        Index("ix_ppt_pages_embedding", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_ppt_pages_text_tsv", "text_tsv", postgresql_using="gin"),
        Index("ix_ppt_pages_file_id", "file_id"),
    )
