"""排除词功能测试：否定语义检索（降权策略）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.search import _apply_exclude_penalty, _hit_exclude, _strip_negative_clause


def test_strip_negative_clause():
    assert _strip_negative_clause("铁塔算法团队，不要跟低空经济有关的") == "铁塔算法团队"
    assert _strip_negative_clause("帮我找铁塔团队情况，不要低空经济") == "帮我找铁塔团队情况"
    assert _strip_negative_clause("无人机巡查，除了消防应用") == "无人机巡查"
    assert _strip_negative_clause("算法能力图") == "算法能力图"  # 无否定保持原样
    # 句首否定：剥离后保留剩余正向意图
    assert "算法团队" in _strip_negative_clause("排除低空经济的页面，找算法团队")
    # 全部是否定从句时回退原查询（避免空串）
    assert _strip_negative_clause("排除低空的页面") == "排除低空的页面"


def test_hit_exclude():
    exclude = ["低空经济", "无人机"]
    item = {"title": "低空经济领域总体规划", "text": "四张网建设", "tags": ""}
    assert _hit_exclude(item, exclude) is True
    item2 = {"title": "中国铁塔创新工作", "text": "算法团队建设", "tags": ""}
    assert _hit_exclude(item2, exclude) is False
    assert _hit_exclude(item2, []) is False  # 空排除列表


def test_apply_exclude_penalty():
    """分级降权：标题命中重降，正文多次命中中降，少量提及轻降"""
    exclude = ["低空经济", "无人机"]
    items = [
        {"title": "低空经济领域总体规划", "text": "", "tags": "", "score": 0.65},  # 标题命中 → ×0.2
        {"title": "算法能力图", "text": "低空经济低空经济低空经济", "tags": "", "score": 0.70},  # 3+次 → ×0.35
        {"title": "中国铁塔创新工作", "text": "低空经济联合创新中心", "tags": "", "score": 0.80},  # 1次 → ×0.65
        {"title": "算法能力图", "text": "622个算法仓", "tags": "", "score": 0.90},  # 未命中 → 保持
    ]
    _apply_exclude_penalty(items, exclude)
    assert abs(items[0]["score"] - 0.65 * 0.20) < 0.01, f"标题命中 ×0.2: {items[0]['score']}"
    assert abs(items[1]["score"] - 0.70 * 0.35) < 0.01, f"3+次 ×0.35: {items[1]['score']}"
    assert abs(items[2]["score"] - 0.80 * 0.65) < 0.01, f"1次 ×0.65: {items[2]['score']}"
    assert items[3]["score"] == 0.90
    # 排序后未命中的最前，轻提及次之，标题命中沉底
    ordered = sorted(items, key=lambda r: r["score"], reverse=True)
    assert ordered[0]["score"] == 0.90 and ordered[-1]["score"] == 0.65 * 0.20


def test_apply_exclude_penalty_no_exclude():
    items = [{"title": "算法能力图", "text": "", "tags": "", "score": 0.65}]
    _apply_exclude_penalty(items, [])
    assert items[0]["score"] == 0.65
