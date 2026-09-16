"""Content-management invariants that do not require a database or provider."""
from types import SimpleNamespace
import pytest
from app.services.page_management import parse_page_selection
from app.services.page_tags import clean_tag, propose_tags
from app.services.duplicates import duplicate_reason, text_overlap
from app.routers.search import _keyword_bonus, _apply_exclude_penalty


@pytest.mark.parametrize('value,count,expected', [('',3,[1,2,3]),('1,3-5',5,[1,3,4,5]),('3,1,3',3,[3,1]),('1，2',2,[1,2])])
def test_selection(value,count,expected):
    assert parse_page_selection(value,count)==expected


@pytest.mark.parametrize('value',['0','5','2-1','1-99999999','全部','1.2','-1'])
def test_invalid_selection(value):
    with pytest.raises(ValueError):parse_page_selection(value,4)


def test_tags_cannot_affect_search_score():
    w={'无人机':{'w':1,'s':['无人机']}}
    assert _keyword_bonus('无人机','摄像机','巡查','无人机',w)==0
    a={'title':'摄像机','text':'巡查','tags':'无人机','score':.8}
    _apply_exclude_penalty([a],['无人机'])
    assert a['score']==.8


def test_tag_limit_and_validation(monkeypatch):
    from app.services import page_tags
    monkeypatch.setattr(page_tags,'chat_json',lambda *a:{'tags':['无人机','无人机','黑飞治理','低空监管','目标识别','轨迹追踪','超出数量',None,'bad,tag']})
    p=SimpleNamespace(title='黑飞监管',text='低空违规目标监测、飞行轨迹追踪及告警的业务能力介绍。'*5,png_path='')
    assert propose_tags(p)==['无人机','黑飞治理','低空监管','目标识别','轨迹追踪']
    assert clean_tag('bad,tag')==''


def test_same_theme_is_not_duplicate():
    a=SimpleNamespace(image_hash='a',text='公安利用无人机巡查地面车辆人员，发现违法停车并进行劝导。'*4)
    b={'image_hash':'b','text':'公安识别无人机违法飞行，定位黑飞操作者并核查处置。'*4}
    assert duplicate_reason(a,b,.99) is None


def test_duplicate_requires_image_or_both_semantic_and_text_evidence():
    a=SimpleNamespace(image_hash='a',text='无人机黑飞告警定位与飞行轨迹追踪'*6)
    assert duplicate_reason(a,{'image_hash':'a','text':''},0)=='页面图像完全一致'
    assert duplicate_reason(a,{'image_hash':'b','text':a.text},.99)
    assert duplicate_reason(a,{'image_hash':'b','text':a.text},.90) is None
    assert text_overlap('','')==0


@pytest.mark.parametrize('similarity,overlap,matched',[
    (.95,.80,True),(.9499,.90,False),(.99,.7999,False),(.976996,.812785,True),
])
def test_duplicate_threshold_boundaries(monkeypatch,similarity,overlap,matched):
    from app.services import duplicates
    monkeypatch.setattr(duplicates,'text_overlap',lambda *args:overlap)
    page=SimpleNamespace(image_hash='old',text='公司介绍正文'*10)
    other={'image_hash':'new','text':'重新排版的公司介绍正文'*10}
    assert bool(duplicate_reason(page,other,similarity)) is matched


@pytest.mark.parametrize('method,path,body',[
    ('GET','/api/management/overview',None),
    ('GET','/api/management/duplicates',None),
    ('POST','/api/management/files/1/pages/delete',{'page_ids':[1]}),
    ('POST','/api/management/duplicates/1/resolve',{'action':'keep_old'}),
    ('POST','/api/management/files/1/retry',None),
])
def test_management_requires_auth(method,path,body):
    from fastapi.testclient import TestClient
    from app.main import app
    client=TestClient(app)
    assert client.request(method,path,json=body).status_code==401
