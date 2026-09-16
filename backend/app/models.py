"""ORM 模型"""
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, BigInteger, Index, UniqueConstraint, ForeignKey, JSON, Float,
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


class ManagedFile(Base):
    """页级编辑标记；原始文件不可变，下载根据当前页面清单组装。"""
    __tablename__ = "managed_files"
    file_id = Column(Integer, ForeignKey("ppt_files.id", ondelete="CASCADE"), primary_key=True)
    revision = Column(Integer, nullable=False, default=1)


class PageSource(Base):
    __tablename__ = "page_sources"
    page_id = Column(Integer, ForeignKey("ppt_pages.id", ondelete="CASCADE"), primary_key=True)
    path = Column(String(1024), nullable=False)
    page_no = Column(Integer, nullable=False)
    page_count = Column(Integer, nullable=False)


class PageTag(Base):
    __tablename__ = "page_tags"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    embedding = Column(Vector(512), nullable=True)


class IngestRun(Base):
    """只有新上传/追加才建检测批次，不自动扫描存量。"""
    __tablename__ = "ingest_runs"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("ppt_files.id", ondelete="CASCADE"), nullable=False, index=True)
    page_ids = Column(JSON, nullable=False, default=list)
    baseline_page_id = Column(Integer, nullable=False, default=0)
    tag_status = Column(String(32), nullable=False, default="pending")
    duplicate_status = Column(String(32), nullable=False, default="pending")
    error_message = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class DuplicatePair(Base):
    __tablename__ = "duplicate_pairs"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("ingest_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    new_page_id = Column(Integer, ForeignKey("ppt_pages.id", ondelete="CASCADE"), nullable=False)
    old_page_id = Column(Integer, ForeignKey("ppt_pages.id", ondelete="CASCADE"), nullable=False)
    similarity = Column(Float, nullable=False)
    reason = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    __table_args__ = (UniqueConstraint("new_page_id", "old_page_id", name="uq_duplicate_pair"),)
