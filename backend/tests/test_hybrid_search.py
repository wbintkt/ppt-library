"""混合检索测试：关键词命中应提升精确匹配页面的排序"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.search import _split_words, _keyword_bonus, _hybrid_sort


def test_split_words_removes_stopwords():
    assert "无人机" in _split_words("找到跟无人机相关的PPT")
    assert "PPT" not in _split_words("找到跟无人机相关的PPT")  # 小写停用
    assert "相关" not in _split_words("找到跟无人机相关的PPT")  # 停用词
    assert "找到" not in _split_words("找到跟无人机相关的PPT")  # 口语词停用
    assert "的" not in _split_words("找到跟无人机相关的PPT")


def test_keyword_bonus_title_gt_body():
    # 标题命中权重 > 正文命中（同一核心词）
    w = {"应急": {"w": 1.0, "s": ["应急"]}}
    b_title = _keyword_bonus("应急", title="应急管理部合作", text="", weights=w)
    b_body = _keyword_bonus("应急", title="", text="与应急管理部签订协议", weights=w)
    assert b_title > b_body > 0
    # 标题+正文叠加：标题命中后正文仍加半权重
    b_both = _keyword_bonus("应急", title="应急管理部", text="应急演练", weights=w)
    assert b_both > b_title
    assert b_both <= 0.90


def test_keyword_bonus_no_hit_zero():
    assert _keyword_bonus("无人机", title="公司简介", text="铁塔站址", weights={"无人机": {"w": 1.0, "s": ["无人机"]}}) == 0


def test_keyword_bonus_synonym_hits():
    """命中同义词也算命中核心词（秸秆禁烧 ≈ 防火）"""
    w = {"防火": {"w": 0.9, "s": ["防火", "烟火", "焚烧", "秸秆禁烧", "消防", "灭火"]}}
    b_syn = _keyword_bonus("防火", title="", text="秸秆禁烧与焚烧监管", weights=w)
    b_none = _keyword_bonus("防火", title="", text="船舶航行监测", weights=w)
    assert b_syn > 0
    assert b_none == 0
    assert b_syn > b_none


def test_keyword_bonus_multi_word_accumulate():
    w = {"应急": {"w": 0.9, "s": ["应急"]}, "无人机": {"w": 0.9, "s": ["无人机"]}}
    b1 = _keyword_bonus("应急 无人机", title="应急", text="", weights=w)
    b2 = _keyword_bonus("应急 无人机", title="应急无人机", text="", weights=w)
    assert b2 > b1 > 0
    assert b2 > 0.60  # 两个词标题命中可超过旧上限


def test_keyword_bonus_core_word_dominates():
    """核心词（防火 0.9）命中标题的加成应远大于泛化词（算法 0.7）命中标题"""
    weights = {"防火": {"w": 0.9, "s": ["防火", "烟火"]}, "算法": {"w": 0.7, "s": ["算法"]}}
    b_fire = _keyword_bonus("防火的算法", title="城市防火高点智能识别", text="", weights=weights)
    b_alg = _keyword_bonus("防火的算法", title="渔政智保 -AI 算法", text="", weights=weights)
    assert b_fire > b_alg, f"核心词加成应大于泛化词: {b_fire} vs {b_alg}"
    # 泛化词命中标题也不应超过正文命中核心词
    b_fire_body = _keyword_bonus("防火的算法", title="", text="秸秆焚烧防火监测", weights=weights)
    assert b_fire_body >= b_alg * 0.5


def test_hybrid_sort_promotes_exact_keyword():
    """精确含关键词的页面应超过纯语义高分页面"""
    results = [
        {"page_id": 1, "title": "低空安全防护体系", "text": "雷达探测 ADS-B 光电跟踪", "score": 0.4895},
        {"page_id": 2, "title": "广泛服务、社会认可", "text": "与农业农村部、应急管理部签订协议", "score": 0.4293},
        {"page_id": 3, "title": "公司简介", "text": "一体两翼战略", "score": 0.4793},
    ]
    ranked = _hybrid_sort(results, "应急", top_k=3)
    assert ranked[0]["page_id"] == 2, "含'应急'关键词的页面应排第一"
    assert ranked[1]["page_id"] == 1


def test_hybrid_sort_respects_top_k():
    results = [
        {"page_id": i, "title": f"标题{i}", "text": "应急" if i == 1 else "普通内容", "score": 0.5 - i * 0.01}
        for i in range(1, 6)
    ]
    ranked = _hybrid_sort(results, "应急", top_k=2)
    assert len(ranked) == 2
