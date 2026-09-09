"""离线回归：完整意图、关键对象、有限等待、缓存和最终Top K。"""
import asyncio
import copy
import json
import os
import sys
from unittest.mock import Mock
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services import intent_reranker as ir
from app.services.search_cache import TTLCache
from app.routers import search as route

QUERY = '公安打击无人机黑飞'
INTENT = {'actor': '公安', 'action': '打击', 'target': '无人机黑飞', 'tool': '',
          'target_terms': [{'term': '黑飞', 'aliases': ['违规飞行']} ]}

@pytest.fixture
def candidates():
    return [
        {'page_id': 1, 'title': '公安使用无人机', 'text': '识别人车、违停', 'score': 1.8},
        {'page_id': 2, 'title': '无人机飞控平台介绍', 'text': '产品中心', 'score': 1.3},
        {'page_id': 3, 'title': '违规飞行监测', 'text': '黑飞发现告警、追踪溯源', 'score': .6},
    ]

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    ir._intent_cache.clear(); ir._score_cache.clear()
    monkeypatch.setattr(ir.settings, 'rerank_enabled', True)
    monkeypatch.setattr(ir.embedder, '_get_api_key', lambda: 'test-key')
    calls=[]
    async def post(path, payload, key, timeout):
        calls.append((path,payload,timeout))
        if 'aigc' in path:
            return {'output': {'choices': [{'finish_reason':'stop','message':{'content':json.dumps(INTENT)}}]}}
        return {'output': {'results': [{'index': i, 'relevance_score': s} for i,s in enumerate([.9,.7,.8])]}}
    monkeypatch.setattr(ir,'post_json',post)
    return calls


def test_missing_target_lowers_wrong_business_without_title_bonus(candidates,isolated):
    original=copy.deepcopy(candidates)
    result,status=ir.rerank(QUERY,candidates)
    assert status=='applied' and [x['page_id'] for x in result]==[3,1,2]
    assert result[0]['score']==result[0]['display_score']==.8
    assert result[1]['score']==.225
    assert '黑飞' in result[1]['rerank_reason']
    assert result[0]['rerank_evidence'] is None
    assert candidates==original
    query=isolated[1][1]['input']['query']
    assert QUERY in query and '作用对象：无人机黑飞' in query


def test_original_negation_never_lost_in_role_summary():
    q='公安治理黑飞，不要实际反制案例'
    assert q in ir._query_with_roles(q,INTENT)
    assert 'PPT页面' in ir._query_with_roles('找黑飞的片子',{})


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(actor='公安局宣传部门'),
    lambda d:d.update(target='无人机黑飞治理案例'),
    lambda d:d.update(tool='PowerPoint'),
    lambda d:d.update(target_terms=[{'term':'案例','aliases':[]}]),
    lambda d:d.update(target_terms=[{'term':'黑飞','aliases':'低空'}]),
])
def test_expanded_or_fabricated_intent_rejected(mutation):
    data=copy.deepcopy(INTENT);mutation(data)
    with pytest.raises(ValueError):ir._parse_intent(data,QUERY)


@pytest.mark.parametrize('rows',[
    [],[{'index':0,'relevance_score':.8}],
    [{'index':0,'relevance_score':.8},{'index':0,'relevance_score':.9}],
    [{'index':True,'relevance_score':.8},{'index':1,'relevance_score':.9}],
    [{'index':2,'relevance_score':.8},{'index':1,'relevance_score':.9}],
    [{'index':0,'relevance_score':float('nan')},{'index':1,'relevance_score':.9}],
    [{'index':0,'relevance_score':float('inf')},{'index':1,'relevance_score':.9}],
    [{'index':0,'relevance_score':True},{'index':1,'relevance_score':.9}],
    [{'index':0,'relevance_score':1.1},{'index':1,'relevance_score':.9}],
])
def test_incomplete_duplicate_or_invalid_scores_rejected(rows):
    with pytest.raises(ValueError):ir._parse_scores({'output':{'results':rows}},2)


def test_out_of_order_provider_results_map_by_index():
    data={'results':[{'index':1,'relevance_score':.9},{'index':0,'relevance_score':.1}]}
    assert ir._parse_scores(data,2)=={0:.1,1:.9}


def test_cache_hits_and_content_changes_invalidate(candidates,isolated):
    one,_=ir.rerank(QUERY,candidates)
    assert len(isolated)==2
    two,_=ir.rerank(QUERY,candidates)
    assert one==two and len(isolated)==2
    candidates[0]['text']='具备黑飞发现与告警能力'
    three,_=ir.rerank(QUERY,candidates)
    assert len(isolated)==3 and three[0]['page_id']==1
    candidates[0]['file_name']='修改后的文件名'
    four,_=ir.rerank(QUERY,candidates)
    assert len(isolated)==3 and four[0]['file_name']=='修改后的文件名'


def test_key_rotation_invalidates_cache(candidates,isolated,monkeypatch):
    ir.rerank(QUERY,candidates)
    monkeypatch.setattr(ir.embedder,'_get_api_key',lambda:'rotated-key')
    ir.rerank(QUERY,candidates)
    assert len(isolated)==4


def test_deadline_cancels_pending_call_without_retries(candidates,monkeypatch):
    cancelled=[];calls=[]
    async def hung(*a):
        calls.append(1)
        try: await asyncio.sleep(20)
        finally: cancelled.append(True)
    monkeypatch.setattr(ir,'post_json',hung)
    monkeypatch.setattr(ir.settings,'rerank_timeout_seconds',.02)
    result,status=ir.rerank(QUERY,candidates)
    assert status=='failed' and result==candidates
    assert cancelled==[True] and len(calls)==1


def test_bad_role_output_still_ranks_original_query(candidates,monkeypatch,isolated):
    async def bad(*a):raise ValueError('invalid role')
    monkeypatch.setattr(ir,'_understand',bad)
    result,status=ir.rerank(QUERY,candidates)
    assert status=='applied'
    assert QUERY in isolated[0][1]['input']['query']


def test_model_failure_restores_all_original_scores(candidates,monkeypatch):
    async def failure(*a):raise RuntimeError('offline')
    monkeypatch.setattr(ir,'post_json',failure)
    result,status=ir.rerank(QUERY,candidates)
    assert status=='failed' and result==candidates
    assert all('rerank_reason' not in x for x in candidates)


def test_skip_disabled_empty_and_no_key(candidates,isolated,monkeypatch):
    monkeypatch.setattr(ir.settings,'rerank_enabled',False)
    assert ir.rerank(QUERY,candidates)[1]=='disabled'
    monkeypatch.setattr(ir.settings,'rerank_enabled',True)
    assert ir.rerank(QUERY,[])[1]=='skipped'
    monkeypatch.setattr(ir.embedder,'_get_api_key',lambda:'')
    assert ir.rerank(QUERY,candidates)[1]=='unavailable'
    assert isolated==[]


def test_noise_is_normalized_without_character_bag_matching():
    parsed=ir._parse_intent(INTENT,QUERY)
    assert ir._target_coverage({'title':'','text':'违\nf070规\n飞行'},parsed)[0]==['黑飞']
    assert ir._target_coverage({'title':'','text':'违\n\uf070规\n飞行'},parsed)[0]==[]
    assert ir._target_coverage({'title':'','text':'飞行黑名单'},parsed)[0]==['黑飞']


def test_cache_bounded_and_returns_copies(monkeypatch):
    import app.services.search_cache as mod
    now=[0];monkeypatch.setattr(mod.time,'monotonic',lambda:now[0])
    cache=TTLCache(capacity=2,ttl=1)
    cache.put('a',[1]);copy=cache.get('a');copy.append(2)
    assert cache.get('a')==[1]
    cache.put('b',[2]);cache.put('c',[3]);assert cache.get('a') is None
    now[0]=2;assert cache.get('c') is None


def setup_route(monkeypatch,candidates):
    for x in candidates:x.update(file_id=1,file_name='测试',page_no=x['page_id'],tags='',category='')
    monkeypatch.setattr(route.embedder,'has_api_key',lambda:True)
    monkeypatch.setattr(route.embedder,'embed_query',lambda q:[.1])
    monkeypatch.setattr(route,'_vector_search',Mock(return_value=candidates))
    monkeypatch.setattr(route,'_fulltext_search',Mock(return_value=candidates))


def test_route_reranks_before_top_k(monkeypatch,candidates):
    setup_route(monkeypatch,candidates)
    result=route.search({'query':QUERY,'top_k':1},_='admin',db=Mock())
    assert result.total==1 and result.items[0].page_id==3
    assert result.rerank_status=='applied'
    assert result.items[0].score==result.items[0].display_score
    assert result.timings_ms['total']>=0


def test_disabled_route_keeps_legacy_fallback(monkeypatch,candidates):
    setup_route(monkeypatch,candidates)
    monkeypatch.setattr(ir.settings,'rerank_enabled',False)
    result=route.search({'query':QUERY},_='admin',db=Mock())
    assert result.rerank_status=='disabled' and result.items[0].page_id==1
    assert result.items[0].display_score==route._score_to_display(result.items[0].score)


def test_vector_failure_can_still_rerank_keyword_candidates(monkeypatch,candidates):
    setup_route(monkeypatch,candidates)
    monkeypatch.setattr(route.embedder,'embed_query',Mock(side_effect=route.embedder.EmbeddingError('test')))
    result=route.search({'query':QUERY,'top_k':1},_='admin',db=Mock())
    assert result.items[0].page_id==3 and result.items[0].embedding_status=='n/a'


def test_keyword_filters_are_mandatory():
    db=Mock();db.execute.return_value.mappings.return_value.all.return_value=[]
    route._fulltext_search(db,'无人机','安防',123,60)
    assert ') AND f.category = :category AND p.file_id = :file_id' in str(db.execute.call_args.args[0])


def test_candidate_budget_preserves_vector_and_keyword_orders():
    rows=[{'page_id':i} for i in range(150)]
    chosen=route._rerank_candidates(rows,list(reversed(rows)),60)
    ids={x['page_id'] for x in chosen}
    assert len(ids)==60 and set(range(30)).issubset(ids) and set(range(120,150)).issubset(ids)
