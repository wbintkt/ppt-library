"""离线协议/路由回归；模型判断被替身控制，不代表真实模型准确率。"""
import copy
import json
import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services import intent_reranker as ir
from app.routers import search as route

QUERY = "找一个公安打击无人机黑飞的片子"


@pytest.fixture
def candidates():
    return [
        {"page_id": 1, "title": "无人机公安巡查", "text": "公安使用无人机识别人车和违停。", "score": 1.5},
        {"page_id": 2, "title": "无人机飞控平台介绍", "text": "产品中心", "score": 1.3},
        {"page_id": 3, "title": "违规飞行告警", "text": "识别黑飞目标，支持轨迹追踪和定位溯源。", "score": 0.7},
    ]


def response():
    return {
        "intent": {"actor": "公安", "action": "打击黑飞", "target": "违规无人机", "purpose": "执法", "exclusions": []},
        "results": [
            {"id": 1, "kind": "mismatch", "score": .95, "evidence": "公安使用无人机识别人车和违停。", "reason": "无人机是工具，监管对象不同"},
            {"id": 2, "kind": "weak", "score": .2, "evidence": "无人机飞控平台介绍", "reason": "仅标题相关，未说明黑飞治理"},
            {"id": 3, "kind": "supporting", "score": .75, "evidence": "识别黑飞目标", "reason": "支持黑飞发现与溯源，未说明公安案例"},
        ],
    }


@pytest.fixture(autouse=True)
def no_external_services(monkeypatch):
    monkeypatch.setattr(ir.settings, "rerank_enabled", True)
    monkeypatch.setattr(ir.embedder, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(ir, "_call_model", Mock(return_value=json.dumps(response(), ensure_ascii=False)))


def test_role_mismatch_cannot_override_full_intent_with_title_bonus(candidates):
    before = copy.deepcopy(candidates)
    ranked, status = ir.rerank(QUERY, candidates)
    assert status == "applied"
    assert [r["page_id"] for r in ranked] == [3, 1, 2]
    assert ranked[1]["score"] == .25  # 模型给高分但判定角色错配，仍执行上限。
    assert ranked[0]["score"] == ranked[0]["display_score"] == .75
    assert candidates == before
    assert ir._call_model.call_args.args[0] == QUERY
    assert "score" not in ir._call_model.call_args.args[1][0]  # 不把旧排名分泄露为评分暗示。


@pytest.mark.parametrize("mutation", [
    lambda d: d["results"].pop(),
    lambda d: d["results"].append(d["results"][0]),
    lambda d: d["results"][0].update(id=2),
    lambda d: d["results"][0].update(id=999),
    lambda d: d["results"][0].update(id=True),
    lambda d: d["results"][0].update(score=float("nan")),
    lambda d: d["results"][0].update(score=float("inf")),
    lambda d: d["results"][0].update(score=True),
    lambda d: d["results"][0].update(score=1.1),
    lambda d: d["results"][0].update(kind="excellent"),
    lambda d: d["results"][2].update(evidence="公安成功反制击落无人机"),
    lambda d: d["results"][2].update(evidence=""),
    lambda d: d["intent"].update(exclusions="无人机"),
])
def test_invalid_output_falls_back_atomically(candidates, mutation):
    data = response()
    mutation(data)
    ir._call_model.return_value = json.dumps(data)
    before = copy.deepcopy(candidates)
    ranked, status = ir.rerank(QUERY, candidates)
    assert status == "failed"
    assert ranked == before == candidates
    assert all("rerank_reason" not in r for r in candidates)


@pytest.mark.parametrize("error", [TimeoutError(), RuntimeError(), ValueError()])
def test_provider_failure_keeps_original_scores(candidates, error):
    ir._call_model.side_effect = error
    assert ir.rerank(QUERY, candidates) == (candidates, "failed")


def test_disabled_missing_key_and_empty_skip_model(candidates, monkeypatch):
    monkeypatch.setattr(ir.settings, "rerank_enabled", False)
    assert ir.rerank(QUERY, candidates)[1] == "disabled"
    monkeypatch.setattr(ir.settings, "rerank_enabled", True)
    monkeypatch.setattr(ir.embedder, "_get_api_key", lambda: "")
    assert ir.rerank(QUERY, candidates)[1] == "unavailable"
    assert ir.rerank(QUERY, [])[1] == "skipped"
    ir._call_model.assert_not_called()


def test_candidate_budget_preserves_both_recall_orders():
    vectors = [{"page_id": i} for i in range(150)]
    hybrid = list(reversed(vectors))
    chosen = route._rerank_candidates(vectors, hybrid, 60)
    ids = [r["page_id"] for r in chosen]
    assert len(ids) == len(set(ids)) == 60
    assert set(range(30)).issubset(ids)
    assert set(range(120, 150)).issubset(ids)


def setup_route(monkeypatch, candidates):
    for item in candidates:
        item.update(file_id=1, file_name="测试素材", page_no=item["page_id"], tags="", category="")
    monkeypatch.setattr(route.embedder, "has_api_key", lambda: True)
    monkeypatch.setattr(route.embedder, "embed_query", lambda q: [0.1])
    monkeypatch.setattr(route, "analyze_query_full", lambda q: ({"无人机": {"w": 1, "s": ["无人机"]}}, []))
    monkeypatch.setattr(route, "_vector_search", Mock(return_value=candidates))
    monkeypatch.setattr(route, "_fulltext_search", Mock(return_value=candidates))


def test_route_reranks_before_top_k_and_keeps_scores_consistent(monkeypatch, candidates):
    setup_route(monkeypatch, candidates)
    result = route.search({"query": QUERY, "top_k": 1}, _="admin", db=Mock())
    assert result.rerank_status == "applied"
    assert result.total == 1
    assert result.items[0].page_id == 3  # 原来第3位，不能先截到top1再重排。
    assert result.items[0].display_score == result.items[0].score == .75
    assert result.items[0].rerank_evidence == "识别黑飞目标"


def test_original_negation_reaches_model_without_lexical_penalty(monkeypatch, candidates):
    setup_route(monkeypatch, candidates)
    query = "找黑飞监测，不要无人机巡逻"
    monkeypatch.setattr(route, "analyze_query_full", lambda q: ({}, ["无人机", "黑飞"]))
    result = route.search({"query": query}, _="admin", db=Mock())
    assert ir._call_model.call_args.args[0] == query
    assert result.items[0].score == .75  # 不能再用泛化排除词削弱正确业务关系。


def test_route_failed_rerank_preserves_legacy_order(monkeypatch, candidates):
    setup_route(monkeypatch, candidates)
    ir._call_model.side_effect = TimeoutError()
    result = route.search({"query": QUERY}, _="admin", db=Mock())
    assert result.rerank_status == "failed"
    assert [r.page_id for r in result.items] == [1, 2, 3]
    assert all(r.rerank_reason is None for r in result.items)
    assert result.items[0].display_score == route._score_to_display(result.items[0].score)


def test_fulltext_fallback_can_still_rerank(monkeypatch, candidates):
    setup_route(monkeypatch, candidates)
    monkeypatch.setattr(route.embedder, "embed_query", Mock(side_effect=route.embedder.EmbeddingError("test")))
    result = route.search({"query": QUERY, "top_k": 1}, _="admin", db=Mock())
    assert result.rerank_status == "applied"
    assert result.items[0].page_id == 3
    assert result.items[0].embedding_status == "n/a"
    assert route._fulltext_search.call_args.args[-1] == 60


def test_text_is_bounded_but_keeps_tail():
    clipped = ir._clip_text("开头" + "中" * 3000 + "末尾黑飞告警", 1800)
    assert clipped.startswith("开头") and clipped.endswith("末尾黑飞告警")
    assert len(clipped) < 1850


def test_keyword_candidates_still_require_category_and_file():
    db = Mock()
    db.execute.return_value.mappings.return_value.all.return_value = []
    route._fulltext_search(db, "无人机", "安防", 123, 60)
    statement = db.execute.call_args.args[0]
    sql = str(statement)
    assert ") AND f.category = :category AND p.file_id = :file_id" in sql
    params = statement.compile().params
    assert params["category"] == "安防" and params["file_id"] == 123


def test_no_key_route_preserves_keyword_search(monkeypatch, candidates):
    setup_route(monkeypatch, candidates)
    monkeypatch.setattr(ir.embedder, "_get_api_key", lambda: "")
    monkeypatch.setattr(route.embedder, "has_api_key", lambda: False)
    result = route.search({"query": QUERY, "top_k": 1}, _="admin", db=Mock())
    assert result.rerank_status == "unavailable"
    assert result.items[0].page_id == 1
    ir._call_model.assert_not_called()
    route._vector_search.assert_not_called()


def test_empty_recall_does_not_call_model(monkeypatch):
    setup_route(monkeypatch, [])
    result = route.search({"query": QUERY}, _="admin", db=Mock())
    assert result.total == 0 and result.rerank_status == "skipped"
    ir._call_model.assert_not_called()


@pytest.mark.parametrize("top_k,expected", [(-5, 1), (1, 1), (500, 50)])
def test_top_k_is_bounded(monkeypatch, top_k, expected):
    candidates = [{"page_id": i, "score": .5, "title": "", "text": ""} for i in range(60)]
    setup_route(monkeypatch, candidates)
    monkeypatch.setattr(ir.settings, "rerank_enabled", False)
    result = route.search({"query": QUERY, "top_k": top_k}, _="admin", db=Mock())
    assert result.total == expected and result.rerank_status == "disabled"
    ir._call_model.assert_not_called()
