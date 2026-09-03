"""搜索显示分测试：display_score 校准（绝对匹配质量）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.search import _normalize_display_scores, _score_to_display


def test_score_to_display_absolute_calibration():
    """绝对质量校准：库里没有好结果时，第一名也不虚高"""
    # 完美匹配（标题精确命中）
    assert _score_to_display(1.75) == 1.0
    assert _score_to_display(1.72) >= 0.98
    # 强匹配（语义 + 核心词）
    assert 0.80 <= _score_to_display(1.34) <= 0.90
    # 弱匹配（库里没有，如"特斯拉财报"）
    assert _score_to_display(0.40) <= 0.15
    assert _score_to_display(0.46) <= 0.20


def test_score_to_display_monotonic():
    """分数越高显示越高（单调）"""
    scores = [0.35, 0.60, 1.00, 1.35, 1.75]
    vals = [_score_to_display(s) for s in scores]
    assert all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))
    # 边界
    assert _score_to_display(0.1) == 0.05  # 低于下限
    assert _score_to_display(2.0) == 1.0   # 高于上限


def test_normalize_display_scores():
    items = [
        {"score": 1.75, "title": "完美"},
        {"score": 0.40, "title": "无关"},
    ]
    _normalize_display_scores(items)
    assert items[0]["display_score"] == 1.0
    assert items[1]["display_score"] <= 0.15


def test_normalize_display_scores_empty():
    items = []
    _normalize_display_scores(items)
    assert items == []
