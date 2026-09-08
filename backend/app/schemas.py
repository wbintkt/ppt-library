"""Pydantic Schema"""
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, ConfigDict


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class FileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    tags: str
    source: str
    file_size: int
    page_count: int
    status: str
    error_message: str
    progress: int
    upload_time: datetime
    update_time: datetime


class FileListResponse(BaseModel):
    total: int
    items: List[FileSummary]


class FileUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    source: Optional[str] = None


class PageSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_id: int
    page_no: int
    title: str
    text: str
    tags: str
    embedding_status: str
    file_name: str = ""
    file_category: str = ""
    file_source: str = ""


class PageListResponse(BaseModel):
    total: int
    items: List[PageSummary]


class SearchResultItem(BaseModel):
    page_id: int
    file_id: int
    file_name: str
    page_no: int
    title: str
    text: str
    tags: str
    score: float
    display_score: float | None = None  # 相关性分（0-1），不是经标注校准的准确率
    rerank_reason: str | None = None
    rerank_evidence: str | None = None
    embedding_status: str
    category: str


class SearchResponse(BaseModel):
    query: str
    total: int
    items: List[SearchResultItem]
    rerank_status: str = "unavailable"


class TaskStatusResponse(BaseModel):
    file_id: int
    status: str
    progress: int
    error_message: str
    page_count: int


class SettingsResponse(BaseModel):
    embed_model: str
    embed_dim: int
    has_api_key: bool
    total_files: int
    total_pages: int
    indexed_pages: int
