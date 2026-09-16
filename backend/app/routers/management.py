"""Page editing, incremental duplicate review and processing status."""
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_
from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import PPTFile, PPTPage, IngestRun, DuplicatePair, ManagedFile
from ..services.page_management import locked_file, remove_pages, new_run, parse_page_selection, page_source
from ..services.slide_merger import _slide_order, _slide_size
from ..tasks import append_pages_task, enrich_file_task, embed_pages_task

router=APIRouter(prefix='/api/management',tags=['management'])


class PageIds(BaseModel):
    page_ids: list[int] = Field(min_length=1,max_length=200)


class ResolveRequest(BaseModel):
    action: str


@router.post('/files/{file_id}/pages/delete')
def delete_selected(file_id:int,body:PageIds,_:str=Depends(get_current_user),db:Session=Depends(get_db)):
    f=locked_file(db,file_id)
    remove_pages(db,f,body.page_ids)
    db.commit()
    return {'ok':True,'page_count':f.page_count}


@router.post('/files/{file_id}/pages/upload')
def append_pages(file_id:int,file:UploadFile=File(...),selection:str=Form(''),
                 _:str=Depends(get_current_user),db:Session=Depends(get_db)):
    f=locked_file(db,file_id)
    if Path(file.filename or '').suffix.lower()!='.pptx':
        raise HTTPException(400,'追加页面请上传 PPTX 文件')
    directory=settings.data_dir/'assets'/f'ppt_{file_id:06d}'
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/f'{uuid.uuid4().hex}.pptx'
    try:
        size=0
        with path.open('wb') as out:
            while chunk:=file.file.read(1024*1024):
                size+=len(chunk)
                if size>settings.max_upload_mb*1024*1024:
                    raise HTTPException(413,f'文件不能超过 {settings.max_upload_mb} MB')
                out.write(chunk)
        try:
            with zipfile.ZipFile(path) as z:
                count=len(_slide_order(z))
                size=_slide_size(z)
            if not count:
                raise ValueError('没有可导入的可见页面')
            selected=parse_page_selection(selection,count)
            first=db.query(PPTPage).filter_by(file_id=file_id).order_by(PPTPage.page_no).first()
            if first:
                with zipfile.ZipFile(page_source(db,first,f)['path']) as z:
                    if size!=_slide_size(z):
                        raise ValueError('页面尺寸与当前文件不一致，请使用相同比例和尺寸的 PPTX')
        except (ValueError,KeyError,zipfile.BadZipFile) as e:
            raise HTTPException(400,str(e))
        run=new_run(db,file_id)
        f.status,f.progress,f.error_message='appending',1,''
        db.commit()
        try:
            append_pages_task.delay(file_id,str(path),selected,run.id)
        except Exception:
            f.status,f.progress='ready',100
            run.tag_status=run.duplicate_status='failed'
            run.error_message='任务队列暂不可用，请重新上传追加页面'
            db.commit()
            raise HTTPException(503,run.error_message)
        return {'ok':True,'run_id':run.id,'pages':len(selected)}
    except Exception:
        path.unlink(missing_ok=True)
        raise


def summary(db,file_id=None):
    query=db.query(IngestRun)
    if file_id is not None:
        query=query.filter_by(file_id=file_id)
    result={}
    for run in query.order_by(IngestRun.id).all():
        result[run.file_id]={'tag_status':run.tag_status,'duplicate_status':run.duplicate_status,
                             'error_message':run.error_message,'pending_count':0,
                             'total_pages':len(run.page_ids),
                             'tagged_pages':db.query(PPTPage).filter(PPTPage.id.in_(run.page_ids),PPTPage.tags!='').count()}
    counts=db.query(DuplicatePair,IngestRun).join(IngestRun,DuplicatePair.run_id==IngestRun.id).filter(DuplicatePair.status=='pending')
    for pair,run in counts.all():
        if run.file_id in result:
            result[run.file_id]['pending_count']+=1
    return result


@router.get('/overview')
def overview(_:str=Depends(get_current_user),db:Session=Depends(get_db)):
    return {'files':summary(db)}


@router.get('/duplicates')
def duplicates(file_id:int=0,_:str=Depends(get_current_user),db:Session=Depends(get_db)):
    q=db.query(DuplicatePair).join(IngestRun).filter(DuplicatePair.status=='pending')
    if file_id:
        q=q.filter(IngestRun.file_id==file_id)
    def page_info(pid):
        p=db.get(PPTPage,pid)
        f=db.get(PPTFile,p.file_id)
        return {'id':p.id,'file_id':p.file_id,'page_no':p.page_no,'title':p.title,'file_name':f.name,'tags':p.tags}
    pairs=q.order_by(DuplicatePair.similarity.desc(),DuplicatePair.id).limit(100).all()
    return {'total':q.count(),'items':[{'id':p.id,'similarity':p.similarity,'reason':p.reason,
                                       'new_page':page_info(p.new_page_id),'old_page':page_info(p.old_page_id)} for p in pairs]}


@router.post('/duplicates/{pair_id}/resolve')
def resolve(pair_id:int,body:ResolveRequest,_:str=Depends(get_current_user),db:Session=Depends(get_db)):
    if body.action not in ('keep_new','keep_old','keep_both'):
        raise HTTPException(400,'请选择保留新页、保留原页或两页都保留')
    pair=db.get(DuplicatePair,pair_id)
    if not pair or pair.status!='pending':
        raise HTTPException(409,'这组页面已处理，请刷新列表')
    if body.action=='keep_both':
        pair.status='dismissed'
    else:
        pid=pair.old_page_id if body.action=='keep_new' else pair.new_page_id
        page=db.get(PPTPage,pid)
        if not page:
            raise HTTPException(409,'页面已删除，请刷新列表')
        f=locked_file(db,page.file_id)
        remove_pages(db,f,[pid])
    db.commit()
    return {'ok':True}


@router.post('/files/{file_id}/retry')
def retry(file_id:int,_:str=Depends(get_current_user),db:Session=Depends(get_db)):
    f=locked_file(db,file_id)
    runs=db.query(IngestRun).filter_by(file_id=file_id).all()
    if f.status=='failed' and not db.get(ManagedFile,file_id) and (not runs or any(not r.page_ids for r in runs)):
        # Resume the original upload run, preserving its pre-upload comparison boundary.
        from .files import reindex_file
        return reindex_file(file_id,_,db)
    if not runs:
        # Explicitly generating labels for old files does not start old-file duplicate scans.
        run=new_run(db,file_id)
        run.page_ids=[p.id for p in db.query(PPTPage).filter_by(file_id=file_id).all()]
        run.duplicate_status='skipped'
    f.status,f.progress='embedding',60
    db.query(PPTPage).filter(PPTPage.file_id==file_id,or_(PPTPage.embedding_status!='done',PPTPage.embedding.is_(None))).update({'embedding_status':'pending'})
    db.commit()
    try:
        embed_pages_task.delay(file_id)
    except Exception:
        f.status,f.progress='ready_limited',100
        f.error_message='任务队列暂不可用，请稍后重试'
        db.commit()
        raise HTTPException(503,f.error_message)
    return {'ok':True}
