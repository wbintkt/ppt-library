"""文件管理路由：上传 / 列表 / 详情 / 更新 / 删除 / 下载 / 重新索引"""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import PPTFile, PPTPage
from ..schemas import FileSummary, FileListResponse, FileUpdateRequest
from ..services import hashing
from ..tasks import parse_ppt_task, embed_pages_task

router = APIRouter(prefix="/api/files", tags=["files"])

ALLOWED_EXTS = {".ppt", ".pptx"}


@router.post("/upload", response_model=FileSummary)
def upload_file(
    file: UploadFile = File(...),
    category: str = Form("未分类"),
    tags: str = Form(""),
    source: str = Form(""),
    _: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail="仅支持 .ppt / .pptx 文件")

    # 保存到临时目录
    tmp_dir = settings.data_dir / "temp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"upload_{uuid.uuid4().hex}{ext}"
    size = 0
    with open(tmp_path, "wb") as out:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            out.write(chunk)
    if size == 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="文件为空")

    # 计算 Hash 并查重
    file_hash = hashing.sha256_file(str(tmp_path))
    dup = db.query(PPTFile).filter(PPTFile.file_hash == file_hash).first()
    if dup:
        tmp_path.unlink(missing_ok=True)
        dup.status = "ready" if dup.page_count else dup.status
        return FileSummary.model_validate(dup)

    # 建记录
    rec = PPTFile(
        name=file.filename,
        stored_name="",  # 占位，id 生成后更新
        file_path="",
        category=category or "未分类",
        tags=tags,
        source=source,
        file_size=size,
        file_hash=file_hash,
        status="parsing",
        progress=1,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    # 移动到正式目录
    stored_name = f"ppt_{rec.id:06d}{ext}"
    final_path = settings.data_dir / "originals" / stored_name
    shutil.move(str(tmp_path), final_path)
    rec.stored_name = stored_name
    rec.file_path = str(final_path)
    db.commit()

    # 派发解析任务
    parse_ppt_task.delay(rec.id)
    return FileSummary.model_validate(rec)


@router.get("", response_model=FileListResponse)
def list_files(
    category: str = "",
    status: str = "",
    q: str = "",
    page: int = 1,
    page_size: int = 50,
    _: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(PPTFile)
    if category:
        query = query.filter(PPTFile.category == category)
    if status:
        query = query.filter(PPTFile.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(PPTFile.name.ilike(like), PPTFile.tags.ilike(like)))
    total = query.count()
    items = (
        query.order_by(PPTFile.upload_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return FileListResponse(total=total, items=[FileSummary.model_validate(i) for i in items])


@router.get("/categories")
def list_categories(_: str = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(PPTFile.category, func.count(PPTFile.id)).group_by(PPTFile.category).all()
    return [{"category": r[0] or "未分类", "count": r[1]} for r in rows]


@router.get("/{file_id}", response_model=FileSummary)
def get_file(file_id: int, _: str = Depends(get_current_user), db: Session = Depends(get_db)):
    rec = db.query(PPTFile).get(file_id)
    if not rec:
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileSummary.model_validate(rec)


@router.patch("/{file_id}", response_model=FileSummary)
def update_file(
    file_id: int,
    body: FileUpdateRequest,
    _: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = db.query(PPTFile).get(file_id)
    if not rec:
        raise HTTPException(status_code=404, detail="文件不存在")
    if body.name is not None:
        rec.name = body.name
    if body.category is not None:
        rec.category = body.category or "未分类"
    if body.tags is not None:
        rec.tags = body.tags
    if body.source is not None:
        rec.source = body.source
    db.commit()
    return FileSummary.model_validate(rec)


@router.delete("/{file_id}")
def delete_file(file_id: int, _: str = Depends(get_current_user), db: Session = Depends(get_db)):
    rec = db.query(PPTFile).get(file_id)
    if not rec:
        raise HTTPException(status_code=404, detail="文件不存在")
    # 删页面记录 + 向量
    db.query(PPTPage).filter_by(file_id=file_id).delete()
    # 删文件与页面目录
    try:
        Path(rec.file_path).unlink(missing_ok=True)
        pages_dir = settings.data_dir / "pages" / f"ppt_{file_id:06d}"
        shutil.rmtree(pages_dir, ignore_errors=True)
    except OSError:
        pass
    db.delete(rec)
    db.commit()
    return {"ok": True}


@router.get("/{file_id}/download")
def download_file(file_id: int, _: str = Depends(get_current_user), db: Session = Depends(get_db)):
    rec = db.query(PPTFile).get(file_id)
    if not rec or not Path(rec.file_path).exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        rec.file_path,
        filename=rec.name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@router.post("/{file_id}/reindex")
def reindex_file(file_id: int, _: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """重新解析 + 向量化（如配置 API Key 后升级语义检索）"""
    rec = db.query(PPTFile).get(file_id)
    if not rec:
        raise HTTPException(status_code=404, detail="文件不存在")
    db.query(PPTPage).filter_by(file_id=file_id).update({"embedding_status": "pending"})
    rec.status = "parsing"
    rec.progress = 1
    rec.error_message = ""
    db.commit()
    parse_ppt_task.delay(file_id)
    return {"ok": True, "message": "已重新加入解析队列"}
