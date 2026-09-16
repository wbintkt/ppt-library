"""Opt-in integration tests using an isolated PostgreSQL database and real PPT parsing.
TEST_MANAGEMENT_DATABASE_URL must contain a database name ending in _test.
"""
import io
import os
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from pptx.util import Inches
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.auth import get_current_user
from app.config import settings
from app.database import Base,get_db
from app.models import PPTFile,PPTPage,PageSource,ManagedFile,IngestRun,DuplicatePair,PageTag
from app import tasks
from app.services import embedder,page_tags

URL=os.getenv('TEST_MANAGEMENT_DATABASE_URL','')
pytestmark=pytest.mark.skipif(not URL,reason='isolated PostgreSQL integration is opt-in')


def deck(labels,hidden=()):
    prs=Presentation()
    for i,label in enumerate(labels):
        s=prs.slides.add_slide(prs.slide_layouts[6])
        s.shapes.add_textbox(Inches(1),Inches(1),Inches(6),Inches(2)).text=label
        if i in hidden:s._element.set('show','0')
    buf=io.BytesIO();prs.save(buf);return buf.getvalue()


@pytest.fixture
def env(tmp_path,monkeypatch):
    engine=create_engine(URL)
    assert engine.url.database.endswith('_test'), 'Never run against the production database'
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine)
    monkeypatch.setattr(tasks,'SessionLocal',Session)
    from app import database
    monkeypatch.setattr(database,'engine',engine)
    monkeypatch.setattr(settings,'data_dir',tmp_path)
    for name in ('temp','originals','pages','assets'):(tmp_path/name).mkdir()
    monkeypatch.setattr(tasks.parse_ppt_task,'delay',MagicMock())
    monkeypatch.setattr(tasks.embed_pages_task,'delay',MagicMock())
    monkeypatch.setattr(tasks.enrich_file_task,'delay',MagicMock())
    monkeypatch.setattr(tasks.append_pages_task,'delay',MagicMock())
    monkeypatch.setattr(embedder,'has_api_key',lambda:True)
    monkeypatch.setattr(embedder,'embed_mixed',lambda inputs:[[1.0]+[0.0]*511 for _ in inputs])
    monkeypatch.setattr(embedder,'embed_text',lambda text:[1.0]+[0.0]*511)
    monkeypatch.setattr(page_tags,'propose_tags',lambda page:['无人机巡查'])
    monkeypatch.setattr(page_tags,'chat_json',lambda *args:{'reuse':None})
    def db():
        with Session() as s:yield s
    old=app.dependency_overrides.copy()
    app.dependency_overrides[get_db]=db
    app.dependency_overrides[get_current_user]=lambda:'test'
    try:yield TestClient(app),Session
    finally:
        app.dependency_overrides.clear();app.dependency_overrides.update(old)
        Base.metadata.drop_all(engine);engine.dispose()


def upload(client,Session,content,legacy=False):
    r=client.post('/api/files/upload',files={'file':('sample.pptx',content)})
    assert r.status_code==200,r.text
    fid=r.json()['id']
    with Session() as db:
        run=db.query(IngestRun).filter_by(file_id=fid).one();rid=run.id
        if legacy:db.delete(run);db.commit()
    tasks.parse_ppt_task.run(fid,None if legacy else rid)
    tasks.embed_pages_task.run(fid)
    if not legacy:tasks.enrich_file_task.run(fid)
    with Session() as db:
        rows=db.query(PPTPage).filter_by(file_id=fid).order_by(PPTPage.page_no).all()
        ids=[p.id for p in rows]
    return fid,ids


def exported(client,ids):
    r=client.post('/api/pages/export',json={'page_ids':ids})
    assert r.status_code==200,r.text
    return [s.shapes[0].text for s in Presentation(io.BytesIO(r.content)).slides]


def test_delete_append_export_stable_ids_and_sources(env):
    c,S=env
    fid,ids=upload(c,S,deck(['隐藏','第一页','第二页','第三页'],hidden=[0]),legacy=True)
    assert c.get('/api/management/overview').json()['files']=={}
    assert c.post(f'/api/management/files/{fid}/pages/delete',json={'page_ids':[ids[1]]}).status_code==200
    with S() as db:
        rows=db.query(PPTPage).filter_by(file_id=fid).order_by(PPTPage.page_no).all()
        assert [p.id for p in rows]==[ids[0],ids[2]]
        assert [p.page_no for p in rows]==[1,2]
        assert db.get(PageSource,ids[2]).page_no==3
    assert exported(c,[ids[2],ids[0]])==['第三页','第一页']
    r=c.post(f'/api/management/files/{fid}/pages/upload',files={'file':('new.pptx',deck(['新一','新二','隐藏'],hidden=[2]))},data={'selection':'2,1'})
    assert r.status_code==200,r.text
    args=tasks.append_pages_task.delay.call_args.args
    tasks.append_pages_task.run(*args)
    tasks.embed_pages_task.run(fid)
    tasks.enrich_file_task.run(fid)
    with S() as db:
        rows=db.query(PPTPage).filter_by(file_id=fid).order_by(PPTPage.page_no).all()
        all_ids=[p.id for p in rows]
        assert len(rows)==4 and all_ids[:2]==[ids[0],ids[2]]
        assert all(p.tags for p in rows[2:])
    assert exported(c,all_ids)==['第一页','第三页','新二','新一']
    download=c.get(f'/api/files/{fid}/download')
    assert [s.shapes[0].text for s in Presentation(io.BytesIO(download.content)).slides]==['第一页','第三页','新二','新一']
    # Validate the merged, cross-source package in the actual import renderer too.
    from app.services.ppt_parser import parse_ppt
    roundtrip=settings.data_dir/'temp'/'current.pptx'
    roundtrip.write_bytes(download.content)
    parsed=parse_ppt(str(roundtrip),str(settings.data_dir/'temp'/'roundtrip'))
    assert len(parsed['pages'])==4
    # Reindex cannot resurrect deleted original pages.
    assert c.post(f'/api/files/{fid}/reindex').status_code==200
    tasks.embed_pages_task.run(fid);tasks.enrich_file_task.run(fid)
    assert exported(c,all_ids)==['第一页','第三页','新二','新一']


def test_incremental_duplicates_wait_then_review(env):
    c,S=env
    text='公安使用无人机巡查地面车辆和人员，识别交通拥堵与违停情况。'*4
    old,old_ids=upload(c,S,deck([text,'旧页']),legacy=True)
    new,new_ids=upload(c,S,deck([text,'新页']))
    with S() as db:
        run=db.query(IngestRun).filter_by(file_id=new).one()
        assert run.duplicate_status=='done'
        pair=db.query(DuplicatePair).filter_by(new_page_id=new_ids[0],old_page_id=old_ids[0]).one()
        pair_id=pair.id
        assert db.query(IngestRun).filter_by(file_id=old).count()==0
    data=c.get(f'/api/management/duplicates?file_id={new}').json()
    assert data['total']==1
    assert c.post(f'/api/management/duplicates/{pair_id}/resolve',json={'action':'keep_new'}).status_code==200
    with S() as db:
        assert db.get(PPTPage,old_ids[0]) is None
        assert db.get(PPTPage,new_ids[0]) is not None
        assert db.get(PPTPage,old_ids[1]).page_no==1
    assert c.get('/api/management/duplicates').json()['total']==0
    assert exported(c,[old_ids[1],new_ids[0]])==['旧页',text]


def test_failed_vectors_do_not_report_no_duplicates_and_tag_reuse(env,monkeypatch):
    c,S=env
    fid,ids=upload(c,S,deck(['第一页','第二页']))
    with S() as db:
        run=db.query(IngestRun).filter_by(file_id=fid).one()
        run.duplicate_status='pending';db.get(PPTPage,ids[1]).embedding_status='failed';db.commit()
    tasks.enrich_file_task.run(fid)
    with S() as db:
        assert db.query(IngestRun).filter_by(file_id=fid).one().duplicate_status=='waiting_vectors'
        assert db.get(PPTFile,fid).status=='ready_limited'
        monkeypatch.setattr(page_tags,'chat_json',lambda *args:{'reuse':'无人机巡查'})
        assert page_tags.canonicalize(db,['无人机巡逻','无人机巡查'])==['无人机巡查']
        db.commit()
        assert db.query(PageTag).count()==1


def test_empty_file_invalid_and_busy_operations(env):
    c,S=env
    fid,ids=upload(c,S,deck(['第一页']),legacy=True)
    assert c.post(f'/api/management/files/{fid}/pages/upload',files={'file':('bad.pptx',b'bad')}).status_code==400
    assert c.post(f'/api/management/files/{fid}/pages/delete',json={'page_ids':[999]}).status_code==404
    assert c.post(f'/api/management/files/{fid}/pages/delete',json={'page_ids':ids}).status_code==200
    assert c.get(f'/api/files/{fid}/download').status_code==400
    assert c.post(f'/api/files/{fid}/reindex').status_code==200
    assert c.post(f'/api/management/files/{fid}/pages/delete',json={'page_ids':ids}).status_code==409
    with S() as db:assert db.query(PPTPage).filter_by(file_id=fid).count()==0


@pytest.mark.parametrize('action',['keep_old','keep_both'])
def test_other_duplicate_decisions(env,action):
    c,S=env
    content='使用无人机完成日常公安巡查并记录识别到的人车事件。'*4
    old,old_ids=upload(c,S,deck([content]),legacy=True)
    new,new_ids=upload(c,S,deck([content,'其他页面']))
    pair=c.get(f'/api/management/duplicates?file_id={new}').json()['items'][0]
    assert c.post(f"/api/management/duplicates/{pair['id']}/resolve",json={'action':action}).status_code==200
    with S() as db:
        assert db.get(PPTPage,old_ids[0]) is not None
        assert (db.get(PPTPage,new_ids[0]) is not None)==(action=='keep_both')
    assert c.get('/api/management/duplicates').json()['total']==0
    assert c.post(f"/api/management/duplicates/{pair['id']}/resolve",json={'action':action}).status_code==409


def test_retry_interrupted_upload_preserves_ingest_run(env):
    c,S=env
    tasks.parse_ppt_task.delay.side_effect=RuntimeError('queue unavailable')
    assert c.post('/api/files/upload',files={'file':('retry.pptx',deck(['重试页面']))}).status_code==503
    with S() as db:
        run=db.query(IngestRun).one()
        fid,rid,baseline=run.file_id,run.id,run.baseline_page_id
        assert not run.page_ids
    tasks.parse_ppt_task.delay.side_effect=None
    assert c.post(f'/api/management/files/{fid}/retry').status_code==200
    assert tasks.parse_ppt_task.delay.call_args.args==(fid,rid)
    tasks.parse_ppt_task.run(fid,rid)
    tasks.embed_pages_task.run(fid)
    tasks.enrich_file_task.run(fid)
    with S() as db:
        run=db.get(IngestRun,rid)
        assert len(run.page_ids)==1 and run.baseline_page_id==baseline
        assert run.tag_status==run.duplicate_status=='done'
