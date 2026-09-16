"""Stable page IDs and immutable source files keep preview, editing and export aligned."""
import hashlib
import re
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func
from ..models import PPTFile, PPTPage, PageSource, ManagedFile, IngestRun

BUSY = {"parsing", "embedding", "enriching", "appending"}


def locked_file(db, file_id):
    f = db.query(PPTFile).filter_by(id=file_id).with_for_update().first()
    if not f:
        raise HTTPException(404, "文件不存在")
    if f.status in BUSY:
        raise HTTPException(409, "文件正在处理，请完成后再编辑页面")
    return f


def remember_sources(db, f):
    state = db.get(ManagedFile, f.id)
    if not state:
        state = ManagedFile(file_id=f.id)
        db.add(state)
        for p in db.query(PPTPage).filter_by(file_id=f.id).all():
            db.add(PageSource(page_id=p.id, path=f.file_path, page_no=p.page_no, page_count=f.page_count))
        db.flush()
    return state


def page_source(db, p, f):
    source = db.get(PageSource, p.id)
    if source:
        return {"path": source.path, "pages": [source.page_no], "page_count": source.page_count}
    if db.get(ManagedFile, f.id):
        raise HTTPException(409, "页面来源记录缺失，请联系管理员")
    return {"path": f.file_path, "pages": [p.page_no], "page_count": f.page_count}


def remove_pages(db, f, ids):
    """Caller holds file row lock; commit all DB changes together. Keep sources for recovery."""
    ids = list(dict.fromkeys(ids))
    rows = db.query(PPTPage).filter_by(file_id=f.id).order_by(PPTPage.page_no).all()
    if not ids or not set(ids).issubset({p.id for p in rows}):
        raise HTTPException(404, "部分所选页面不存在或不属于该文件，请刷新后重试")
    state = remember_sources(db, f)
    remaining = [p for p in rows if p.id not in ids]
    # Avoid transient collisions with uq_file_page, preserving the surviving page IDs.
    for p in rows:
        p.page_no = -p.id
    db.flush()
    for p in rows:
        if p.id in ids:
            db.delete(p)
    db.flush()
    for no, p in enumerate(remaining, 1):
        p.page_no = no
    f.page_count = len(remaining)
    state.revision += 1
    f.file_hash = hashlib.sha256(f"managed:{f.id}:{state.revision}".encode()).hexdigest()
    db.flush()


def new_run(db, file_id):
    run = IngestRun(file_id=file_id, baseline_page_id=db.query(func.max(PPTPage.id)).scalar() or 0)
    db.add(run)
    db.flush()
    return run


def parse_page_selection(value, count):
    if not value.strip():
        return list(range(1, count + 1))
    result = []
    for token in re.split(r"[,，\s]+", value.strip()):
        if not re.fullmatch(r"\d+(?:-\d+)?", token):
            raise ValueError("页码格式不正确，请填写如 1,3-5")
        bounds = [int(x) for x in token.split('-')]
        start, end = bounds[0], bounds[-1]
        if not 1 <= start <= end <= count:
            raise ValueError(f"页码超出范围，此文件共 {count} 个可见页面")
        result.extend(range(start, end + 1))
    return list(dict.fromkeys(result))
