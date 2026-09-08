"""使用真实 DashScope SDK 构造/解析消息，仅替换 HTTP 传输；不调用外部模型。"""
import json
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services import intent_reranker as ir


@pytest.mark.parametrize("status,finish,timeout,expected", [
    (200, "stop", False, "applied"),
    (200, "length", False, "failed"),
    (429, "stop", False, "failed"),
    (200, "stop", True, "failed"),
])
def test_sdk_wire_contract(monkeypatch, status, finish, timeout, expected):
    observed = []
    content = {
        "intent": {"actor": "", "action": "发现", "target": "违规无人机", "purpose": "", "exclusions": []},
        "results": [{"id": 1, "kind": "direct", "score": .9, "reason": "直接支持黑飞发现", "evidence": "黑飞发现告警"}],
    }

    def send(session, request, **kwargs):
        observed.append((request, kwargs))
        if timeout:
            raise requests.exceptions.ReadTimeout("simulated")
        response = requests.Response()
        response.status_code = status
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps({
            "request_id": "test", "code": "Throttling" if status == 429 else "",
            "message": "test", "usage": {},
            "output": {"choices": [{"finish_reason": finish, "message": {
                "role": "assistant", "content": json.dumps(content, ensure_ascii=False),
            }}]},
        }).encode()
        return response

    monkeypatch.setattr(requests.sessions.Session, "send", send)
    monkeypatch.setattr(ir.settings, "rerank_enabled", True)
    monkeypatch.setattr(ir.embedder, "_get_api_key", lambda: "test-key")
    items = [{"page_id": 1, "title": "黑飞发现告警", "text": "", "score": .3}]
    ranked, state = ir.rerank("找黑飞发现告警内容", items)
    assert state == expected
    assert len(observed) == 1
    request, kwargs = observed[0]
    assert kwargs["timeout"] == ir.settings.rerank_timeout_seconds
    body = json.loads(request.body)
    assert body["model"] == ir.settings.rerank_model
    assert body["parameters"]["enable_thinking"] is False
    assert body["parameters"]["response_format"] == {"type": "json_object"}
    assert "request_timeout" not in body["parameters"]
    payload = json.loads(body["input"]["messages"][1]["content"])
    assert payload["query"] == "找黑飞发现告警内容"
    assert payload["candidates"][0]["id"] == 1
    assert ranked[0]["score"] == (.9 if expected == "applied" else .3)
