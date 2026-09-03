"""任务状态 / 系统设置 / 统计 路由"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import PPTFile, PPTPage, AppSetting
from ..schemas import TaskStatusResponse, SettingsResponse
from ..services import embedder

router = APIRouter(prefix="/api", tags=["misc"])


@router.get("/tasks/{file_id}", response_model=TaskStatusResponse)
def task_status(file_id: int, _: str = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.query(PPTFile).get(file_id)
    if not f:
        raise HTTPException(status_code=404, detail="文件不存在")
    return TaskStatusResponse(
        file_id=f.id, status=f.status, progress=f.progress,
        error_message=f.error_message, page_count=f.page_count,
    )


@router.get("/settings", response_model=SettingsResponse)
def get_settings(_: str = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(AppSetting).filter_by(key="DASHSCOPE_API_KEY").first()
    has_key = bool(row and row.value.strip()) or bool(embedder.has_api_key())
    total_files = db.query(func.count(PPTFile.id)).scalar() or 0
    total_pages = db.query(func.count(PPTPage.id)).scalar() or 0
    indexed_pages = db.query(func.count(PPTPage.id)).filter(PPTPage.embedding_status == "done").scalar() or 0
    return SettingsResponse(
        embed_model=embedder.settings.embed_model,
        embed_dim=embedder.settings.embed_dim,
        has_api_key=has_key,
        total_files=total_files,
        total_pages=total_pages,
        indexed_pages=indexed_pages,
    )


class ApiKeyRequest(BaseModel):
    dashscope_api_key: str = ""


@router.post("/settings")
def save_api_key(body: ApiKeyRequest, _: str = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(AppSetting).filter_by(key="DASHSCOPE_API_KEY").first()
    key = body.dashscope_api_key.strip()
    if row:
        row.value = key
    else:
        db.add(AppSetting(key="DASHSCOPE_API_KEY", value=key))
    db.commit()
    embedder._invalidate_key_cache()
    return {"ok": True, "has_api_key": bool(key)}


@router.get("/stats")
def stats(_: str = Depends(get_current_user), db: Session = Depends(get_db)):
    total_files = db.query(func.count(PPTFile.id)).scalar() or 0
    total_pages = db.query(func.count(PPTPage.id)).scalar() or 0
    indexed = db.query(func.count(PPTPage.id)).filter(PPTPage.embedding_status == "done").scalar() or 0
    ready_files = db.query(func.count(PPTFile.id)).filter(PPTFile.status.in_(["ready", "ready_limited"])).scalar() or 0
    return {
        "total_files": total_files,
        "total_pages": total_pages,
        "indexed_pages": indexed,
        "ready_files": ready_files,
        "vector_mode": embedder.has_api_key(),
    }
