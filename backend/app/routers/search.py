"""语义检索路由（核心）

流程：query → 向量/关键词召回（含元数据过滤）→ 完整意图重排 → Top K
降级：无 API Key 或向量检索异常时，自动回退 PostgreSQL 全文检索。
"""
import logging
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

import jieba
jieba.setLogLevel(60)

_STOP_WORDS = {
    "的", "了", "一页", "这个", "那个", "什么", "怎么", "哪个", "找一",
    "帮我", "请", "需要", "一个", "一下", "相关", "那种", "这种", "图片", "页面",
    "找到", "找", "跟", "请问", "哪些", "如何", "怎样", "给我", "看看", "介绍",
    "有没有", "有关", "关于", "一下", "ppt", "pptx",
}

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..schemas import SearchResponse, SearchResultItem
from ..services import embedder
from ..services.intent_reranker import rerank
from ..services.query_analyzer import analyze_query, _rule_exclude

logger = logging.getLogger("ppt.search")
router = APIRouter(prefix="/api/search", tags=["search"])


def _vector_search(db: Session, qvec: list, category: str, file_id: int, tags: str, limit: int) -> list:
    """pgvector cosine 相似度检索"""
    where = ["p.embedding IS NOT NULL"]
    params = {"qvec": str(qvec), "limit": limit}
    if category:
        where.append("f.category = :category")
        params["category"] = category
    if file_id:
        where.append("p.file_id = :file_id")
        params["file_id"] = file_id
    if tags:
        where.append("f.tags ILIKE :tags")
        params["tags"] = f"%{tags}%"
    sql = f"""
        SELECT p.id AS page_id, p.file_id, p.page_no, p.title, p.text, p.tags,
               f.name AS file_name, f.category,
               1 - (p.embedding <=> CAST(:qvec AS vector)) AS score
        FROM ppt_pages p
        JOIN ppt_files f ON f.id = p.file_id
        WHERE {' AND '.join(where)}
        ORDER BY p.embedding <=> CAST(:qvec AS vector)
        LIMIT :limit
    """
    rows = db.execute(sa_text(sql).bindparams(**params)).mappings().all()
    return [dict(r) for r in rows]


# 排除相关
# 命中排除词降权系数（次数分级）：标题命中或多次命中=主题相关，重降；少量提及=轻降。
_EXCLUDE_TITLE_FACTOR = 0.20   # 标题命中（页面主题就是排除概念）
_EXCLUDE_MANY_FACTOR = 0.35    # 正文命中 3+ 次（排除内容占比高）
_EXCLUDE_FEW_FACTOR = 0.65     # 正文命中 1-2 次（仅顺带提及）

def _strip_negative_clause(query: str) -> str:
    """剥离否定从句，得到纯正向查询（用于向量编码，避免排除概念污染向量）。
    例："铁塔算法团队，不要跟低空经济有关的" → "铁塔算法团队"
    例："无人机，除了消防的" → "无人机"
    例："排除低空经济的页面，找算法团队" → "找算法团队"
    """
    import re
    # 1) 句中/句尾否定从句（逗号/分号后）
    patterns = [
        r"[，,。；;\s]*(不要|别|莫|请勿)[^，,。；;]{0,40}?(有关|相关|内容|页面|PPT|的)?$",
        r"[，,。；;\s]*除了[^，,。；;]{0,40}?(外|之外|以外|的内容|的页面)?$",
        r"[，,。；;\s]*(排除|剔除|去掉|不含|不要含)[^，,。；;]{0,40}$",
        r"[，,。；;\s]*[与跟和][^，,。；;]{0,40}?无关$",
    ]
    cleaned = query
    for pat in patterns:
        cleaned = re.sub(pat, "", cleaned)
    # 2) 句首否定："排除X(的页面/内容)，要Y" 或 "不要X的"
    head_patterns = [
        r"^(排除|剔除|去掉|不含|不要|别要)[^，,。；;]{0,30}?(的页面|的内容|的PPT|的)?[，,。；;\s]*",
        r"^不要[^，,。；;]{0,30}?(有关|相关|的)[，,。；;\s]*",
    ]
    for pat in head_patterns:
        cleaned = re.sub(pat, "", cleaned)
    cleaned = cleaned.strip(" ，,。；;、:：")
    return cleaned or query


def _hit_exclude(item: dict, exclude: list) -> bool:
    """页面是否命中任一排除词（标题/正文）"""
    if not exclude:
        return False
    hay = f"{(item.get('title') or '')}\n{(item.get('text') or '')}".lower()
    return any(str(e).lower() in hay for e in exclude if e)


def _hit_exclude_count(item: dict, exclude: list) -> int:
    """页面命中的排除词总次数（标题/正文）"""
    if not exclude:
        return 0
    hay = f"{(item.get('title') or '')}\n{(item.get('text') or '')}".lower()
    return sum(hay.count(str(e).lower()) for e in exclude if e)


def _apply_exclude_penalty(items: list[dict], exclude: list) -> None:
    """命中排除词的页面按命中程度分级降权：
    - 标题命中：页面主题即排除概念 → 重降（×0.2）
    - 正文命中 3+ 次：排除内容占比高 → 中降（×0.35）
    - 正文命中 1-2 次：仅顺带提及 → 轻降（×0.65）
    未命中保持原分。目的：排除概念主题页沉底，但真正相关的页（顺带提及）不被误杀。
    """
    if not exclude:
        return
    for it in items:
        title_l = (it.get("title") or "").lower()
        title_hit = any(str(e).lower() in title_l for e in exclude if e)
        if title_hit:
            factor = _EXCLUDE_TITLE_FACTOR
        else:
            n = _hit_exclude_count(it, exclude)
            if n >= 3:
                factor = _EXCLUDE_MANY_FACTOR
            elif n >= 1:
                factor = _EXCLUDE_FEW_FACTOR
            else:
                factor = 1.0
        if factor < 1.0:
            it["score"] = round(float(it.get("score") or 0.0) * factor, 4)


def _split_words(query: str) -> list:
    """jieba 中文分词 + 过滤停用词，得到检索关键词（含原整句作为高权重项）"""
    tokens = [w.strip() for w in jieba.lcut(query) if w.strip()]
    # 大小写归一后过滤停用词
    words = [w for w in tokens if len(w) >= 2 and w.lower() not in _STOP_WORDS and not w.isspace()]
    # 去重保序
    seen, out = set(), []
    for w in words:
        wl = w.lower()
        if wl not in seen:
            seen.add(wl)
            out.append(w)
    if not out:
        out = [query]
    # 整句本身也作为一个高权重关键词（若长度合适）
    if len(query) <= 30 and query not in out:
        out.insert(0, query)
    return out[:8]


# 混合检索：关键词命中权重（标题 > 正文；标签不参与评分）
_KW_TITLE = 0.45   # 标题命中一个关键词
_KW_TEXT = 0.12    # 正文命中一个关键词
_KW_CAP = 0.90     # 关键词加成上限（避免关键词淹没语义）

# 非核心词（权重 < 0.8）加成折扣：次要/泛化词命中只给小幅加成，
# 避免"算法"这类泛化词逆转向量主排序
_CORE_WEIGHT = 0.8
_NONCORE_MULT = 0.25


def _word_mult(weight: float) -> float:
    """按词权重分级：核心词全额，次要词折扣，泛化词微额"""
    if weight >= _CORE_WEIGHT:
        return 1.0
    if weight >= 0.5:
        return _NONCORE_MULT
    return 0.1


def _keyword_bonus(query: str, title: str = "", text: str = "", tags: str = "", weights: dict | None = None) -> float:
    """关键词命中加成：标题命中权重最高，正文次之；标签不参与评分。
    同一关键词标题与正文都命中时叠加（标题是强信号）。
    weights 结构：{词: {"w": 权重, "s": [同义词]}}，命中同义词也算命中。
    返回 0 ~ _KW_CAP 的加成值，供混合排序使用。
    """
    if weights is None:
        weights = analyze_query(query)
    if not weights:
        words = _split_words(query)
        weights = {w: {"w": 1.0, "s": [w]} for w in words}
    title_l = (title or "").lower()
    text_l = (text or "").lower()
    bonus = 0.0
    for w, info in weights.items():
        if isinstance(info, dict):
            weight = info.get("w", 0.5)
            syns = info.get("s") or [w]
        else:  # 兼容纯数字
            weight = float(info)
            syns = [w]
        mult = _word_mult(weight)
        hit_title = any(s.lower() in title_l for s in syns)
        hit_text = any(s.lower() in text_l for s in syns)
        if hit_title:
            bonus += _KW_TITLE * mult
        if hit_text and not hit_title:
            bonus += _KW_TEXT * mult
        elif hit_text and hit_title:
            bonus += _KW_TEXT * 0.5 * mult  # 标题+正文都命中：正文按半权重叠加
    return min(bonus, _KW_CAP)


def _hybrid_sort(vector_items: list[dict], query: str, top_k: int = 20, weights: dict | None = None) -> list[dict]:
    """混合排序：向量相似度 + 关键词命中加成。
    向量候选集内，精确含关键词的页面获得加成，避免被语义相近页面淹没。
    score 为最终排序分（可 >1）；display_score 保留纯向量相似度（0-1）供展示。
    """
    if weights is None:
        weights = analyze_query(query)
    for it in vector_items:
        vec = float(it.get("score") or 0.0)
        bonus = _keyword_bonus(query, it.get("title"), it.get("text"), it.get("tags"), weights)
        it["display_score"] = round(max(0.0, min(1.0, vec)), 4)
        it["score"] = round(vec + bonus, 4)
        it["keyword_bonus"] = round(bonus, 4)
    items = sorted(vector_items, key=lambda r: r["score"], reverse=True)
    return items[:top_k]


def _fulltext_search(db: Session, query: str, category: str, file_id: int, limit: int) -> list:
    """降级/兜底：多关键词 ILIKE 匹配（对中文友好）+ 词频打分"""
    words = _split_words(query)
    where = []
    filters = []
    score_parts = []
    params = {"limit": limit}
    for i, w in enumerate(words):
        p = f"w{i}"
        params[p] = f"%{w}%"
        where.append(f"(p.title ILIKE :{p} OR p.text ILIKE :{p})")
        score_parts.append(f"CASE WHEN p.title ILIKE :{p} THEN 3.0 ELSE 0 END + CASE WHEN p.text ILIKE :{p} THEN 1.0 ELSE 0 END")
    if category:
        filters.append("f.category = :category")
        params["category"] = category
    if file_id:
        filters.append("p.file_id = :file_id")
        params["file_id"] = file_id
    score_sql = " + ".join(score_parts)
    where_sql = " AND ".join([f"({' OR '.join(where)})", *filters])
    sql = f"""
        SELECT p.id AS page_id, p.file_id, p.page_no, p.title, p.text, p.tags,
               f.name AS file_name, f.category,
               ({score_sql}) AS score
        FROM ppt_pages p
        JOIN ppt_files f ON f.id = p.file_id
        WHERE {where_sql}
        ORDER BY score DESC, p.page_no
        LIMIT :limit
    """
    rows = db.execute(sa_text(sql).bindparams(**params)).mappings().all()
    return [dict(r) for r in rows]


# 显示分校准：混合分 → 匹配百分比（0-1）的经验映射。
# 基于真实数据标定（混合分 = 向量相似度 0-1 + 关键词加成 0-0.9）：
#   0.35 → 5%   几乎无关（库里没有相关内容）
#   0.60 → 30%  弱相关
#   1.00 → 60%  语义相关（无关键词命中）
#   1.35 → 85%  强匹配（语义 + 核心词命中）
#   1.75 → 100% 完美匹配（标题精确命中）
_DISPLAY_CALIB = [(0.35, 0.05), (0.60, 0.30), (1.00, 0.60), (1.35, 0.85), (1.75, 1.00)]


def _score_to_display(score: float) -> float:
    """混合分 → 显示匹配度（0-1），分段线性插值校准"""
    if score <= _DISPLAY_CALIB[0][0]:
        return _DISPLAY_CALIB[0][1]
    if score >= _DISPLAY_CALIB[-1][0]:
        return _DISPLAY_CALIB[-1][1]
    for (x0, y0), (x1, y1) in zip(_DISPLAY_CALIB, _DISPLAY_CALIB[1:]):
        if x0 <= score < x1:
            t = (score - x0) / (x1 - x0)
            return round(y0 + (y1 - y0) * t, 4)
    return _DISPLAY_CALIB[-1][1]


def _normalize_display_scores(items: list[dict]) -> None:
    """显示分校准：混合分 → 绝对匹配百分比（0-1）。
    反映真实匹配质量：库里没有好结果时第一名也不会虚高到 100%。
    """
    for r in items:
        s = float(r.get("score") or 0.0)
        r["display_score"] = _score_to_display(s)


def _rerank_candidates(vector_items: list[dict], hybrid_items: list[dict], limit: int) -> list[dict]:
    """向量序与关键词序交替取候选，防止标题加分提前挤掉业务相关页。"""
    chosen = {}
    for vector, hybrid in zip(vector_items, hybrid_items):
        for item in (vector, hybrid):
            chosen.setdefault(item["page_id"], item)
            if len(chosen) == limit:
                return list(chosen.values())
    return list(chosen.values())


@router.post("", response_model=SearchResponse)
def search(
    body: dict,
    _: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="查询内容不能为空")
    if len(query) > 1000:
        raise HTTPException(status_code=400, detail="查询内容请控制在1000字以内")
    started = time.monotonic()
    category = (body.get("category") or "").strip()
    file_id = int(body.get("file_id") or 0)
    limit = max(1, min(int(body.get("top_k") or settings.search_top_k), 50))

    items = []
    mode = "vector"
    has_key = embedder.has_api_key()
    candidate_limit = settings.rerank_candidate_limit
    fulltext_limit = candidate_limit if has_key and settings.rerank_enabled else limit
    # 候选选择只需本地词项；完整关系由后续重排判断，不再先串行生成同义词列表。
    weights = {word: {"w": 1.0, "s": [word]} for word in _split_words(query)}
    exclude = _rule_exclude(query)
    if has_key:
        try:
            # 剥离否定从句后用正向意图编码向量（避免排除概念把目标页拉高）
            positive_q = _strip_negative_clause(query)
            qvec = embedder.embed_query(positive_q)
            # 取更大的候选集（关键词加成可能让后位页面上升）
            vector_items = _vector_search(db, qvec, category, file_id, "", max(limit * 3, candidate_limit))
            hybrid_items = _hybrid_sort(vector_items, query, top_k=len(vector_items), weights=weights)
            fallback_items = hybrid_items[:max(limit * 2, 30)]
            items = _rerank_candidates(vector_items, hybrid_items, candidate_limit)
        except embedder.EmbeddingError as e:
            logger.warning("vector search failed, fallback to fulltext: %s", e)
            mode = "fulltext"
            items = _fulltext_search(db, query, category, file_id, fulltext_limit)
            fallback_items = items[:limit]
    else:
        mode = "fulltext"
        items = _fulltext_search(db, query, category, file_id, limit)
        fallback_items = items[:limit]

    # 必须使用原始完整问题；重排成功后不叠加关键词/排除词分，避免再次丢失业务关系。
    recall_ms = round((time.monotonic() - started) * 1000)
    rerank_started = time.monotonic()
    items, rerank_status = rerank(query, items)
    rerank_ms = round((time.monotonic() - rerank_started) * 1000)
    if rerank_status == "applied":
        items = items[:limit]
    else:
        _apply_exclude_penalty(fallback_items, exclude)
        items = sorted(fallback_items, key=lambda r: r["score"], reverse=True)[:limit]
        _normalize_display_scores(items)

    results = [
        SearchResultItem(
            page_id=r["page_id"], file_id=r["file_id"], file_name=r["file_name"],
            page_no=r["page_no"], title=r["title"] or f"第{r['page_no']}页",
            text=r["text"] or "", tags=r["tags"] or "", score=round(float(r["score"]), 4),
            display_score=r.get("display_score"),
            rerank_reason=r.get("rerank_reason"),
            rerank_evidence=r.get("rerank_evidence"),
            embedding_status="done" if mode == "vector" else "n/a",
            category=r["category"] or "",
        )
        for r in items
    ]
    timings = {"recall": recall_ms, "rerank": rerank_ms, "total": round((time.monotonic() - started) * 1000)}
    logger.info("search timing: %s status=%s results=%s", timings, rerank_status, len(results))
    return SearchResponse(query=query, total=len(results), items=results, rerank_status=rerank_status,
                          timings_ms=timings)
