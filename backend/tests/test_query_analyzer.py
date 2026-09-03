"""查询理解模块测试：LLM 解析 / 排除词 / 缓存 / IDF 兜底"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import query_analyzer as qa


def test_parse_llm_response_duplicated_output():
    """qwen-flash 偶发重复输出多份 JSON，应只取第一份"""
    one = '{"keywords": [{"word": "防火", "weight": 0.9, "synonyms": ["防火","烟火"]}]}'
    content = one + "\n\n" + one + "\n\n" + one
    r = qa._parse_llm_response(content)
    words, exclude = r
    assert words == {"防火": {"w": 0.9, "s": ["防火", "烟火"]}}
    assert exclude == []


def test_parse_llm_response_plain_json():
    content = '{"keywords": [{"word": "防火", "weight": 0.9, "synonyms": ["防火","烟火"]}, {"word": "算法", "weight": 0.5, "synonyms": ["算法"]}]}'
    words, exclude = qa._parse_llm_response(content)
    assert words["防火"]["w"] == 0.9
    assert "烟火" in words["防火"]["s"]
    assert words["算法"]["w"] == 0.5


def test_parse_llm_response_with_markdown_fence():
    content = '```json\n{"keywords": [{"word": "无人机", "weight": 0.8}, {"word": "算法", "weight": 0.6}]}\n```'
    words, exclude = qa._parse_llm_response(content)
    assert words["无人机"]["w"] == 0.8
    assert "无人机" in words["无人机"]["s"]  # 无 synonyms 时自动补原词


def test_parse_llm_response_invalid():
    assert qa._parse_llm_response("抱歉，我无法回答") is None
    assert qa._parse_llm_response("") is None
    assert qa._parse_llm_response('{"keywords": "notalist"}') is None


def test_parse_llm_response_filters_short_words():
    content = '{"keywords": [{"word": "的", "weight": 0.9}, {"word": "防火", "weight": 0.8, "synonyms": ["防火"]}]}'
    words, exclude = qa._parse_llm_response(content)
    assert words == {"防火": {"w": 0.8, "s": ["防火"]}}


def test_parse_llm_response_with_exclude():
    """LLM 输出 exclude 时正确解析（含同义词扩展）"""
    content = '{"keywords": [{"word": "算法团队", "weight": 0.9}], "exclude": ["低空经济", "无人机"]}'
    words, exclude = qa._parse_llm_response(content)
    assert "算法团队" in words
    assert "低空经济" in exclude and "无人机" in exclude
    # 带同义词的 exclude 项
    content2 = '{"keywords": [], "exclude": [{"word": "消防", "synonyms": ["消防","灭火","火情"]}]}'
    _, exclude2 = qa._parse_llm_response(content2)
    assert "消防" in exclude2 and "灭火" in exclude2 and "火情" in exclude2


def test_analyze_llm_priority(monkeypatch):
    """LLM 正常时用 LLM 结果"""
    monkeypatch.setattr(qa, "_get_redis", lambda: None)  # 关缓存
    monkeypatch.setattr(qa, "_llm_analyze", lambda q: ({"防火": {"w": 0.9, "s": ["防火"]}, "算法": {"w": 0.5, "s": ["算法"]}}, []))
    r = qa.analyze_query("关于防火的算法介绍")
    assert r["防火"]["w"] == 0.9


def test_analyze_fallback_idf(monkeypatch):
    """LLM 失败时用 IDF 兜底，且关键领域词权重更高"""
    monkeypatch.setattr(qa, "_get_redis", lambda: None)
    monkeypatch.setattr(qa, "_llm_analyze", lambda q: None)
    # mock IDF：防火出现少→IDF高，算法出现多→IDF低
    monkeypatch.setattr(qa, "_compute_idf", lambda: {"防火": 2.8, "算法": 1.1, "识别": 0.6})
    r = qa.analyze_query("关于防火的算法介绍")
    assert "防火" in r and "算法" in r
    assert r["防火"]["w"] > r["算法"]["w"], f"IDF 兜底应让'防火'权重大于'算法': {r}"


def test_analyze_uses_cache(monkeypatch):
    """命中缓存时不调 LLM（新缓存格式 words/exclude）"""
    calls = []

    class FakeRedis:
        def __init__(self, data):
            self.data = data

        def get(self, key):
            return self.data.get(key)

        def setex(self, key, ttl, val):
            self.data[key] = val

    fake = FakeRedis({qa._cache_key("测试查询"): json.dumps({"words": {"防火": 1.0}, "exclude": []})})
    monkeypatch.setattr(qa, "_get_redis", lambda: fake)
    monkeypatch.setattr(qa, "_llm_analyze", lambda q: calls.append(q) or ({"防火": 0.5}, []))
    r = qa.analyze_query("测试查询")
    assert r == {"防火": 1.0}
    assert calls == [], "命中缓存不应调用 LLM"


def test_analyze_full_exclude(monkeypatch):
    """analyze_query_full 返回 (words, exclude)，IDF 兜底 + 规则排除"""
    monkeypatch.setattr(qa, "_get_redis", lambda: None)
    monkeypatch.setattr(qa, "_llm_analyze", lambda q: None)
    monkeypatch.setattr(qa, "_compute_idf", lambda: {"防火": 1.0, "算法": 1.0})
    words, exclude = qa.analyze_query_full("防火算法，不要跟低空经济有关的")
    assert "防火" in words
    assert any("低空" in e for e in exclude), f"规则兜底应识别排除词: {exclude}"


def test_idf_compute_against_db():
    """对真实库计算 IDF：防火应比识别更稀有"""
    idf = qa._compute_idf()
    assert "防火" in idf and "识别" in idf
    assert idf["防火"] > idf["识别"], f"防火({idf.get('防火')}) 应比 识别({idf.get('识别')}) 更稀有"
