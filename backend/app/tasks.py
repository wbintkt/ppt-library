"""Celery 后台任务：PPT 解析 + Embedding 批处理"""
import logging
import hashlib
import shutil
import tempfile
from pathlib import Path

from celery import Celery
from sqlalchemy import text as sa_text

from .config import settings
from .database import SessionLocal
from .models import PPTFile, PPTPage, IngestRun, PageSource, ManagedFile
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
def parse_ppt_task(file_id: int, run_id: int | None = None) -> dict:
    """解析 PPT：转换 PNG + 提取文本 + 建页面记录"""
    db = SessionLocal()
    work_dir = None
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
                elif existing:
                    existing.title, existing.text, existing.png_path = p['title'], p['text'], str(dst_png)
                    existing.image_hash, existing.embedding_status, existing.embedding = image_hash, 'pending', None
                    existing.tags = ''
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

            if run_id:
                run = db.get(IngestRun, run_id)
                if run:
                    run.page_ids = [p.id for p in db.query(PPTPage).filter_by(file_id=file_id).all()]
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
            db.rollback()
            _set_file(db, file_id, status="failed", error_message=f"解析异常: {e}")
            return {"ok": False, "error": str(e)}
    finally:
        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
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
            for run in db.query(IngestRun).filter_by(file_id=file_id).all():
                if run.duplicate_status not in ('done','skipped'):
                    run.duplicate_status='waiting_vectors'
                if run.tag_status!='done':
                    run.tag_status='failed'
                    run.error_message='未配置模型密钥，配置后可重试标签和相似检测'
            db.commit()
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
        db.rollback()
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
    has_runs = db.query(IngestRun).filter_by(file_id=file_id).count()
    if has_runs:
        f.status = 'enriching'
        f.progress = 96
    db.commit()
    if has_runs:
        enrich_file_task.delay(file_id)


def _refresh_tsv(db, file_id: int):
    """刷新全文检索向量（降级/混合检索用）"""
    db.execute(sa_text(
        "UPDATE ppt_pages SET text_tsv = to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(text,'')) "
        "WHERE file_id = :fid"
    ).bindparams(fid=file_id))
    db.commit()


@celery_app.task(name='ppt.append_pages')
def append_pages_task(file_id: int, path: str, selection: list[int], run_id: int):
    from .services.page_management import remember_sources
    db = SessionLocal()
    work_dir = tempfile.mkdtemp(prefix='append_', dir=str(settings.data_dir / 'temp'))
    try:
        f = db.get(PPTFile, file_id)
        run = db.get(IngestRun, run_id)
        if not f or not run:
            return
        if run.page_ids:  # Redelivery after a successful import must not append twice.
            embed_pages_task.delay(file_id, run.page_ids)
            return
        result = parse_ppt(path, work_dir)
        if any(n < 1 or n > result['page_count'] for n in selection):
            raise ValueError('追加页面与解析结果不一致')
        state = remember_sources(db, f)
        images = settings.data_dir / 'pages' / f'ppt_{file_id:06d}' / f'append_{run_id}'
        images.mkdir(parents=True, exist_ok=True)
        ids = []
        for n in selection:
            source = result['pages'][n - 1]
            image = images / f'page_{n:03d}.png'
            shutil.copy2(source['png_path'], image)
            page = PPTPage(file_id=file_id,page_no=f.page_count+len(ids)+1,
                           title=source['title'],text=source['text'],png_path=str(image),
                           image_hash=hashing.sha256_file(str(image)),embedding_status='pending')
            db.add(page); db.flush()
            db.add(PageSource(page_id=page.id,path=path,page_no=n,page_count=result['page_count']))
            ids.append(page.id)
        f.page_count += len(ids)
        f.file_size += Path(path).stat().st_size
        state.revision += 1
        f.file_hash = hashlib.sha256(f'managed:{f.id}:{state.revision}'.encode()).hexdigest()
        run.page_ids = ids
        f.status, f.progress = 'embedding', 55
        db.commit()
        _refresh_tsv(db,file_id)
        embed_pages_task.delay(file_id, ids)
    except Exception as e:
        db.rollback()
        logger.exception('append failed')
        _set_file(db,file_id,status='ready' if db.query(PPTPage).filter_by(file_id=file_id).count() else 'failed',
                  error_message=f'追加未完成：{e}',progress=100)
        run=db.get(IngestRun,run_id)
        if run:
            run.tag_status=run.duplicate_status='failed'
            run.error_message=f'追加未完成：{e}'
            db.commit()
    finally:
        shutil.rmtree(work_dir,ignore_errors=True)
        db.close()


@celery_app.task(name='ppt.enrich')
def enrich_file_task(file_id: int):
    from .services import page_tags, duplicates
    from .database import engine
    # A dedicated connection keeps the session advisory lock through page commits.
    with engine.connect() as lock:
        acquired = lock.execute(sa_text('SELECT pg_try_advisory_lock(17312, :id)'),{'id':file_id}).scalar()
        if not acquired:
            return
        db=SessionLocal()
        try:
            f=db.get(PPTFile,file_id)
            if not f:
                return
            runs=db.query(IngestRun).filter_by(file_id=file_id).order_by(IngestRun.id).all()
            for run in runs:
                if not run.page_ids:
                    continue
                if run.duplicate_status not in ('done','skipped'):
                    try:
                        duplicates.detect(db,run)
                        db.commit()
                    except Exception:
                        db.rollback()
                        logger.exception('duplicate detection failed')
                        run=db.get(IngestRun,run.id)
                        run.duplicate_status='failed'
                        run.error_message='相似检测未完成，请重试'
                        db.commit()
                if run.tag_status == 'done':
                    continue
                run.tag_status='running'
                run.error_message=''
                db.commit()
                errors=0
                for pid in run.page_ids:
                    page=db.get(PPTPage,pid)
                    if not page or page.tags:
                        continue
                    try:
                        names=page_tags.propose_tags(page)
                        names=page_tags.canonicalize(db,names)
                        page.tags=','.join(names)
                        db.commit()
                    except Exception:
                        db.rollback()
                        errors+=1
                        logger.exception('page tagging failed: %s',pid)
                run=db.get(IngestRun,run.id)
                run.tag_status='failed' if errors else 'done'
                if errors:
                    run.error_message=f'{errors} 页标签未生成，可稍后重试'
                db.commit()
            f=db.get(PPTFile,file_id)
            failed=db.query(PPTPage).filter(PPTPage.file_id==file_id,PPTPage.embedding_status!='done').count()
            f.status='ready_limited' if failed else 'ready'
            f.progress=100
            f.error_message=f'{failed} 页向量未就绪，相似检测需向量全部完成后运行' if failed else ''
            db.commit()
        except Exception:
            db.rollback()
            logger.exception('page enrichment failed')
            _set_file(db,file_id,status='ready_limited',progress=100,
                      error_message='页面标签或相似检测未完成，请重试未完成项')
        finally:
            db.close()
            lock.execute(sa_text('SELECT pg_advisory_unlock(17312, :id)'),{'id':file_id})
