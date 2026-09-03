"""页面路由：页面列表 / 单页 / PNG 预览 / 合并导出"""
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import or_, func, text as sa_text
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import PPTFile, PPTPage
from ..schemas import PageSummary, PageListResponse
from ..services.slide_merger import merge_pages, MergeError

router = APIRouter(prefix="/api/pages", tags=["pages"])


def _to_summary(p: PPTPage, file: PPTFile) -> PageSummary:
    return PageSummary(
        id=p.id, file_id=p.file_id, page_no=p.page_no, title=p.title,
        text=p.text, tags=p.tags, embedding_status=p.embedding_status,
        file_name=file.name if file else "",
        file_category=file.category if file else "",
        file_source=file.source if file else "",
    )


@router.get("", response_model=PageListResponse)
def list_pages(
    file_id: int = 0,
    category: str = "",
    q: str = "",
    page: int = 1,
    page_size: int = 60,
    _: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(PPTPage)
    if file_id:
        query = query.filter(PPTPage.file_id == file_id)
    if category:
        sub = db.query(PPTFile.id).filter(PPTFile.category == category).subquery()
        query = query.filter(PPTPage.file_id.in_(sub))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(PPTPage.title.ilike(like), PPTPage.text.ilike(like)))
    total = query.count()
    rows = (
        query.order_by(PPTPage.file_id.desc(), PPTPage.page_no)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    file_map = {f.id: f for f in db.query(PPTFile).all()}
    items = [_to_summary(p, file_map.get(p.file_id)) for p in rows]
    return PageListResponse(total=total, items=items)


@router.post("/export")
def export_pages(
    body: dict,
    _: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """勾选的页面合并导出为一份 .pptx（跨文件，保持原始样式，原生可编辑）"""
    page_ids = body.get("page_ids") or []
    if not isinstance(page_ids, list) or not page_ids:
        raise HTTPException(status_code=400, detail="请至少选择一页")
    if len(page_ids) > 200:
        raise HTTPException(status_code=400, detail="单次最多导出 200 页")

    # 按传入顺序取页面（含所属文件）
    rows = (
        db.query(PPTPage)
        .filter(PPTPage.id.in_(page_ids))
        .all()
    )
    by_id = {p.id: p for p in rows}
    pages = [by_id[i] for i in page_ids if i in by_id]
    if not pages:
        raise HTTPException(status_code=404, detail="所选页面不存在")

    # 按文件分组，保持勾选顺序
    file_map = {f.id: f for f in db.query(PPTFile).all()}
    groups: dict[int, dict] = {}
    for p in pages:
        f = file_map.get(p.file_id)
        if not f or not f.file_path or not Path(f.file_path).exists():
            continue
        g = groups.setdefault(p.file_id, {"path": f.file_path, "pages": []})
        g["pages"].append(p.page_no)
    if not groups:
        raise HTTPException(status_code=404, detail="所选页面的原始 PPT 文件不存在")

    sources = [{"path": g["path"], "pages": g["pages"]} for g in groups.values()]

    # 原始页面抽取合并（保持样式/比例/可编辑）
    out_path = settings.data_dir / "temp" / f"export_{uuid.uuid4().hex}.pptx"
    try:
        merge_pages(sources, out_path)
    except MergeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    buf = out_path.read_bytes()
    out_path.unlink(missing_ok=True)
    filename = f"页面合集_{datetime.now():%Y%m%d_%H%M%S}.pptx"
    return Response(
        content=buf,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/{page_id}", response_model=PageSummary)
def get_page(page_id: int, _: str = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(PPTPage).get(page_id)
    if not p:
        raise HTTPException(status_code=404, detail="页面不存在")
    f = db.query(PPTFile).get(p.file_id)
    return _to_summary(p, f)


@router.get("/{page_id}/similar")
def similar_pages(
    page_id: int,
    top_k: int = 6,
    _: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """相似页面推荐：基于页面向量的 pgvector 最近邻（排除自身）
    无向量时回退为同文件相邻页。
    """
    p = db.query(PPTPage).get(page_id)
    if not p:
        raise HTTPException(status_code=404, detail="页面不存在")
    if p.embedding is not None:
        qvec = "[" + ",".join(str(x) for x in p.embedding) + "]"
        sql = """
            SELECT p.id AS page_id, p.file_id, p.page_no, p.title, p.text,
                   f.name AS file_name,
                   1 - (p.embedding <=> CAST(:qvec AS vector)) AS score
            FROM ppt_pages p
            JOIN ppt_files f ON f.id = p.file_id
            WHERE p.embedding IS NOT NULL AND p.id != :pid
            ORDER BY p.embedding <=> CAST(:qvec AS vector)
            LIMIT :limit
        """
        rows = db.execute(
            sa_text(sql).bindparams(qvec=qvec, pid=page_id, limit=top_k)
        ).mappings().all()
    else:
        # 无向量：同文件相邻页
        rows = db.execute(
            sa_text("""
                SELECT p.id AS page_id, p.file_id, p.page_no, p.title, p.text,
                       f.name AS file_name, 0.0 AS score
                FROM ppt_pages p
                JOIN ppt_files f ON f.id = p.file_id
                WHERE p.file_id = :fid AND p.id != :pid
                ORDER BY ABS(p.page_no - :pno), p.page_no
                LIMIT :limit
            """).bindparams(fid=p.file_id, pid=page_id, pno=p.page_no, limit=top_k)
        ).mappings().all()
    return [
        {
            "page_id": r["page_id"], "file_id": r["file_id"], "page_no": r["page_no"],
            "title": r["title"] or f"第{r['page_no']}页", "text": r["text"] or "",
            "file_name": r["file_name"], "score": round(float(r["score"]), 4),
        }
        for r in rows
    ]


@router.get("/{page_id}/image")
def page_image(page_id: int, _: str = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(PPTPage).get(page_id)
    if not p or not p.png_path or not Path(p.png_path).exists():
        raise HTTPException(status_code=404, detail="页面图片不存在")
    return FileResponse(
        p.png_path, media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
