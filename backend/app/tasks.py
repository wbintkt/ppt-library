"""Celery 后台任务：PPT 解析 + Embedding 批处理"""
import logging
import shutil
import tempfile
from pathlib import Path

from celery import Celery
from sqlalchemy import text as sa_text

from .config import settings
from .database import SessionLocal
from .models import PPTFile, PPTPage
from .services import embedder, hashing
from .services.ppt_parser import parse_ppt, PPTParseError

logger = logging.getLogger("ppt.tasks")

celery_app = Celery(
    "ppt_library",
    broker=settings.redis_url,
    backend=settings.celery_backend_url,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
)
celery_app.conf.update(
    task_time_limit=3600,
    task_soft_time_limit=3300,
    worker_max_tasks_per_child=10,  # 防内存泄漏
    broker_connection_retry_on_startup=True,
)

EMBED_BATCH = 4  # 每批图片数


def _set_file(db, file_id: int, **kw):
    f = db.query(PPTFile).get(file_id)
    if f:
        for k, v in kw.items():
            setattr(f, k, v)
        db.commit()


@celery_app.task(name="ppt.parse")
def parse_ppt_task(file_id: int) -> dict:
    """解析 PPT：转换 PNG + 提取文本 + 建页面记录"""
    db = SessionLocal()
    try:
        f = db.query(PPTFile).get(file_id)
        if not f:
            return {"ok": False, "error": "文件记录不存在"}
        try:
            _set_file(db, file_id, status="parsing", progress=5, error_message="")
            work_dir = tempfile.mkdtemp(prefix="ppt_work_", dir=str(settings.data_dir / "temp"))
            result = parse_ppt(f.file_path, work_dir)
            # 页面目录：/data/ppt-library/pages/ppt_{file_id}/
            pages_dir = settings.data_dir / "pages" / f"ppt_{file_id:06d}"
            if pages_dir.exists():
                shutil.rmtree(pages_dir)
            pages_dir.mkdir(parents=True, exist_ok=True)

            total = result["page_count"]
            for i, p in enumerate(result["pages"]):
                # 移动 PNG 到正式目录
                dst_png = pages_dir / f"page_{p['page_no']:03d}.png"
                shutil.move(p["png_path"], dst_png)
                image_hash = hashing.sha256_file(str(dst_png))
                # 已存在且 hash 未变的页面：跳过重新 embedding
                existing = db.query(PPTPage).filter_by(
                    file_id=file_id, page_no=p["page_no"]).first()
                if existing and existing.image_hash == image_hash:
                    db.query(PPTPage).filter_by(
                        file_id=file_id, page_no=p["page_no"]).update({
                            "title": p["title"],
                            "text": p["text"],
                            "png_path": str(dst_png),
                        })
                else:
                    page = PPTPage(
                        file_id=file_id,
                        page_no=p["page_no"],
                        title=p["title"],
                        text=p["text"],
                        png_path=str(dst_png),
                        image_hash=image_hash,
                        embedding_status="pending",
                    )
                    db.add(page)
                if (i + 1) % 5 == 0:
                    db.commit()
                    _set_file(db, file_id, progress=min(50, 5 + int(45 * (i + 1) / total)))
            db.commit()

            # 刷新全文检索 tsvector
            _refresh_tsv(db, file_id)

            _set_file(db, file_id, page_count=total, progress=55)
            # 触发 embedding（异步）
            embed_pages_task.delay(file_id)
            return {"ok": True, "page_count": total}
        except PPTParseError as e:
            _set_file(db, file_id, status="failed", error_message=str(e))
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.exception("parse error")
            _set_file(db, file_id, status="failed", error_message=f"解析异常: {e}")
            return {"ok": False, "error": str(e)}
    finally:
        db.close()


@celery_app.task(name="ppt.embed_pages")
def embed_pages_task(file_id: int, page_ids: list = None) -> dict:
    """批量生成页面 Embedding"""
    db = SessionLocal()
    try:
        f = db.query(PPTFile).get(file_id)
        if not f:
            return {"ok": False, "error": "文件记录不存在"}

        q = db.query(PPTPage).filter_by(file_id=file_id, embedding_status="pending")
        if page_ids:
            q = q.filter(PPTPage.id.in_(page_ids))
        pages = q.order_by(PPTPage.page_no).all()
        if not pages:
            # 没有待处理的页面：直接收尾
            _finish(db, file_id)
            return {"ok": True, "embedded": 0}

        if not embedder.has_api_key():
            # 无 API Key：文本检索降级可用
            _set_file(db, file_id, status="ready_limited", progress=100,
                      error_message="未配置 DASHSCOPE_API_KEY，当前为全文检索模式，配置后自动升级为语义检索")
            return {"ok": True, "embedded": 0, "limited": True}

        _set_file(db, file_id, status="embedding", progress=60)
        total = len(pages)
        done = 0
        failed = 0
        # 分批调用（图+文本混合输入，同模型同空间）
        for i in range(0, total, EMBED_BATCH):
            batch = pages[i:i + EMBED_BATCH]
            inputs = []
            for p in batch:
                inputs.append({"text": (p.title + "\n" + p.text)[:8000]})
                inputs.append({"image": p.png_path})
            try:
                vecs = embedder.embed_mixed(inputs)
                for j, p in enumerate(batch):
                    text_vec = vecs[j * 2]
                    img_vec = vecs[j * 2 + 1]
                    # 文本与图片向量取平均，融合页面语义
                    merged = [(a + b) / 2 for a, b in zip(text_vec, img_vec)]
                    p.embedding = merged
                    p.embedding_status = "done"
            except embedder.EmbeddingError as e:
                logger.warning("embed batch failed: %s", e)
                for p in batch:
                    p.embedding_status = "failed"
                failed += len(batch)
                _set_file(db, file_id, error_message=str(e))
            done += len(batch)
            db.commit()
            _set_file(db, file_id, progress=min(95, 60 + int(35 * (i + len(batch)) / total)))

        db.commit()
        _finish(db, file_id)
        return {"ok": True, "embedded": done, "failed": failed}
    except Exception as e:
        logger.exception("embed error")
        _set_file(db, file_id, status="failed", error_message=f"向量化异常: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def _finish(db, file_id: int):
    f = db.query(PPTFile).get(file_id)
    if not f:
        return
    failed = db.query(PPTPage).filter_by(file_id=file_id, embedding_status="failed").count()
    done = db.query(PPTPage).filter_by(file_id=file_id, embedding_status="done").count()
    if failed > 0 and done == 0:
        f.status = "failed"
        f.error_message = f.error_message or "向量化失败"
    elif failed > 0:
        f.status = "ready"
        f.error_message = f"部分页面向量化失败（{failed} 页），可重新索引"
    else:
        f.status = "ready"
        f.error_message = ""
    f.progress = 100
    db.commit()


def _refresh_tsv(db, file_id: int):
    """刷新全文检索向量（降级/混合检索用）"""
    db.execute(sa_text(
        "UPDATE ppt_pages SET text_tsv = to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(text,'')) "
        "WHERE file_id = :fid"
    ).bindparams(fid=file_id))
    db.commit()
