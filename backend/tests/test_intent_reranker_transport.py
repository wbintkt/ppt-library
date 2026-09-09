"""真实HTTP客户端配合内存传输，确认请求格式、认证、错误和取消。"""
import asyncio
import json
import os
import sys
import pytest
import httpx
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services import model_client as client
from app.services import intent_reranker as ir


def test_native_request_contract(monkeypatch):
    calls=[]
    async def post(path,payload,key,timeout):
        calls.append((path,payload,key))
        return {'output':{'results':[{'index':0,'relevance_score':.8}]}}
    async def roles(*a):return ir._parse_intent({'actor':'公安','action':'打击','target':'黑飞','tool':'','target_terms':[]},'公安打击黑飞')
    monkeypatch.setattr(ir,'post_json',post);monkeypatch.setattr(ir,'_understand',roles)
    monkeypatch.setattr(ir.settings,'rerank_model','qwen3.7-text-rerank')
    out=asyncio.run(ir._rank('公安打击黑飞',[{'id':9,'title':'黑飞','text':'识别告警'}],'test-key'))
    path,payload,key=calls[0]
    assert path=='/api/v1/services/rerank/text-rerank/text-rerank'
    assert key=='test-key' and payload['parameters']['top_n']==1
    assert '业务动作：打击' in payload['input']['query']
    assert payload['input']['documents']==['黑飞\n识别告警']
    assert out[9]['score']==.8


@pytest.mark.parametrize('status',[200,429,503])
def test_http_client_without_retries(monkeypatch,status):
    calls=[];real=httpx.AsyncClient
    def handler(request):
        calls.append(request)
        assert request.headers['Authorization']=='Bearer test-key'
        assert json.loads(request.content)=={'model':'test'}
        return httpx.Response(status,json={'ok':True})
    monkeypatch.setattr(client.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    if status==200:
        assert asyncio.run(client.post_json('/test',{'model':'test'},'test-key',1))=={'ok':True}
    else:
        with pytest.raises(httpx.HTTPStatusError):asyncio.run(client.post_json('/test',{'model':'test'},'test-key',1))
    assert len(calls)==1


def test_http_total_deadline_cancels_transport(monkeypatch):
    closed=[];real=httpx.AsyncClient
    async def handler(request):
        try:await asyncio.sleep(20)
        finally:closed.append(True)
    monkeypatch.setattr(client.httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(TimeoutError):asyncio.run(client.post_json('/test',{},'test-key',.02))
    assert closed==[True]
