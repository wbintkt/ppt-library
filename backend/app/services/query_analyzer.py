"""查询理解：LLM 解析用户问题，提取关键词及权重（语义主次）。

- 优先：百炼 qwen-plus 分析查询 → {"词": 权重}
- 兜底：IDF 统计加权（词在库中出现越少，权重越高）
- 缓存：Redis 按查询哈希缓存 24h，避免重复调用
"""
import hashlib
import json
import math
import time

from ..config import settings
from ..services import embedder

# LLM 分析用模型（flash 级：快、便宜，查询理解任务够用）
_ANALYZE_MODEL = "qwen-flash"
_CACHE_TTL = 24 * 3600
_REDIS_PREFIX = "ppt:qanalyze:"

_PROMPT = """你是 PPT 素材检索系统的查询理解器。用户会输入一句检索问题，请从中提取 1~4 个关键词，并为每个关键词打分（0~1），表示它在检索中的重要性。

要求：
1. 只提取有实际检索价值的词（名词/领域词），忽略"找、帮我、跟、相关、介绍、关于、一下"等口语/虚词
2. 权重体现语义主次：核心主题词给高分（0.7~1.0），次要限定词给中分（0.4~0.7），泛化词给低分（0.1~0.4）
3. 为每个关键词给出 3~8 个同义词/近义词/相关词（含原词），用于匹配页面上意思相同但写法不同的内容。例如"防火"的同义词：["防火","烟火","焚烧","秸秆禁烧","消防","灭火","火情"]；"无人机"的同义词：["无人机","低空飞行器","巡飞","机巢"]
4. 如果用户表达了否定/排除意图（如"不要…的""排除…""除了…""别含…""与…无关""不含…"），把被排除的概念提取到 exclude 列表（含同义词/相关写法），这些词【不要】放进 keywords
5. 只输出 JSON，不要任何其他文字

输出格式：{"keywords": [{"word": "防火", "weight": 0.9, "synonyms": ["防火","烟火","焚烧","秸秆禁烧","消防","灭火","火情"]}, {"word": "算法", "weight": 0.5, "synonyms": ["算法","识别模型","AI能力"]}], "exclude": ["低空经济", "无人机"]}
没有排除意图时 exclude 为空列表：[]
"""


def _get_redis():
    try:
        import redis
        return redis.Redis.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        return None


def _cache_key(query: str) -> str:
    return _REDIS_PREFIX + hashlib.md5(query.encode()).hexdigest()


def _extract_first_json(text: str) -> str | None:
    """提取文本中第一个完整的 JSON 对象（括号配对，容忍字符串内花括号）。
    qwen-flash 偶发重复输出多份 JSON，需取第一份。
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _parse_llm_response(content: str) -> tuple | None:
    """解析 LLM 输出，容忍 markdown 代码块、重复输出等包裹。
    返回 (words, exclude)：words 为 {词: {"w": 权重, "s": [同义词...]}}，exclude 为排除词列表。
    失败返回 None
    """
    if not content:
        return None
    obj = _extract_first_json(content)
    if not obj:
        return None
    try:
        data = json.loads(obj)
    except json.JSONDecodeError:
        return None
    kws = data.get("keywords")
    if not isinstance(kws, list):
        return None
    result = {}
    for item in kws:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word", "")).strip()
        try:
            weight = float(item.get("weight", 0.5))
        except (TypeError, ValueError):
            weight = 0.5
        if not word or len(word) < 2 or weight <= 0:
            continue
        syns = item.get("synonyms")
        syn_list = []
        if isinstance(syns, list):
            for s in syns:
                s = str(s).strip()
                if s and len(s) >= 2:
                    syn_list.append(s)
        if word not in syn_list:
            syn_list.insert(0, word)
        result[word] = {"w": max(0.0, min(1.0, weight)), "s": syn_list[:12]}
    # 排除词：LLM 返回的 exclude 列表（含扩展同义词写法）
    exclude = []
    raw_ex = data.get("exclude")
    if isinstance(raw_ex, list):
        for item in raw_ex:
            if isinstance(item, dict):
                # 兼容带同义词的 exclude 项
                w = str(item.get("word", "")).strip()
                if len(w) >= 2:
                    exclude.append(w)
                    syns = item.get("synonyms")
                    if isinstance(syns, list):
                        exclude.extend(s for s in (str(x).strip() for x in syns) if len(s) >= 2)
            else:
                s = str(item).strip()
                if len(s) >= 2:
                    exclude.append(s)
    return (result, list(dict.fromkeys(exclude))) if result or exclude else None


def _llm_analyze(query: str) -> tuple | None:
    """调用百炼 LLM 分析查询，返回 (words, exclude)；失败返回 None"""
    api_key = embedder._get_api_key()
    if not api_key:
        return None
    try:
        from dashscope import Generation
        resp = Generation.call(
            model=_ANALYZE_MODEL,
            messages=[
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": query},
            ],
            api_key=api_key,
            result_format="message",
            max_tokens=400,
            temperature=0.1,
        )
        if resp.status_code != 200:
            return None
        content = resp.output.choices[0].message.content
        return _parse_llm_response(content)
    except Exception:
        return None


# ---- IDF 兜底 ----

_idf_cache = {"ts": 0.0, "data": None}
_IDF_TTL = 600.0


def _compute_idf() -> dict:
    """统计库内每个词的文档频率并算 IDF（缓存 10 分钟）"""
    now = time.time()
    if _idf_cache["data"] is not None and now - _idf_cache["ts"] < _IDF_TTL:
        return _idf_cache["data"]
    try:
        from ..database import SessionLocal
        from ..models import PPTPage
        from sqlalchemy import text as sa_text
        db = SessionLocal()
        try:
            total = db.query(PPTPage).count()
            # 简单取词：用库里所有页面的文本分词统计不划算，这里用高频词表近似
            # 直接查常见领域词的 df
            common = ["算法", "无人机", "应急", "防火", "烟火", "识别", "监测", "感知",
                      "秸秆", "渔政", "高点", "低点", "城市", "治理", "视频", "模型",
                      "大模型", "算力", "铁塔", "低空", "安全", "监控", "摄像头", "巡检",
                      "电力", "水利", "环保", "国土", "交通", "公安", "海洋", "船舶"]
            idf = {}
            for w in common:
                cnt = db.query(PPTPage).filter(
                    (PPTPage.title.ilike(f"%{w}%")) | (PPTPage.text.ilike(f"%{w}%"))
                ).count()
                idf[w] = math.log(total / max(cnt, 1)) if cnt else 3.0
            _idf_cache["data"] = idf
            _idf_cache["ts"] = now
            return idf
        finally:
            db.close()
    except Exception:
        return {}


def _idf_analyze(query: str) -> dict:
    """IDF 兜底：查询词按 IDF 归一化权重。返回 {词: {"w":权重,"s":[同义词]}}"""
    import jieba
    jieba.setLogLevel(60)
    tokens = [w.strip() for w in jieba.lcut(query) if w.strip()]
    words = [w for w in tokens if len(w) >= 2 and w.lower() not in _STOP_WORDS_SKIP and not w.isspace()]
    if not words:
        return {}
    idf = _compute_idf()
    weights = {}
    for w in words:
        weights[w] = idf.get(w, 1.0)
    # 归一化到最大 1.0
    mx = max(weights.values(), default=1.0)
    return {k: {"w": round(v / mx, 2), "s": [k]} for k, v in weights.items()}


# 与 search.py 保持一致的停用词（避免 IDF 兜底引入口语词）
_STOP_WORDS_SKIP = {
    "的", "了", "一页", "这个", "那个", "什么", "怎么", "哪个", "找一",
    "帮我", "请", "需要", "一个", "一下", "相关", "那种", "这种", "图片", "页面",
    "找到", "找", "跟", "请问", "哪些", "如何", "怎样", "给我", "看看", "介绍",
    "有没有", "有关", "关于", "ppt", "pptx",
}


def analyze_query(query: str) -> dict:
    """对外入口：分析查询 → {词: {"w":权重,"s":同义词}}。LLM 优先，缓存，IDF 兜底。
    注意：仅返回正向关键词（不含 exclude），供 keyword bonus 使用。
    需要排除词的场景请用 analyze_query_full。
    """
    words, _ = analyze_query_full(query)
    return words


def analyze_query_full(query: str) -> tuple:
    """完整分析：返回 (words, exclude)。words 为正向关键词字典，exclude 为排除概念词列表。
    排除词也尽量扩展同义词（供页面文本匹配）。
    """
    query = (query or "").strip()
    if not query:
        return {}, []

    # 缓存（存完整结构）
    r = _get_redis()
    if r is not None:
        try:
            cached = r.get(_cache_key(query))
            if cached:
                data = json.loads(cached)
                if data:
                    return data.get("words", {}), data.get("exclude", [])
        except Exception:
            pass

    # LLM
    parsed = _llm_analyze(query)
    words, exclude = {}, []
    if parsed:
        words, exclude = parsed
    if not words:
        words = _idf_analyze(query)
    if not exclude:
        exclude = _rule_exclude(query)

    # 写缓存
    if (words or exclude) and r is not None:
        try:
            payload = json.dumps({"words": words, "exclude": exclude}, ensure_ascii=False)
            r.setex(_cache_key(query), _CACHE_TTL, payload)
        except Exception:
            pass
    return words, exclude


def _rule_exclude(query: str) -> list:
    """规则兜底：检测明确的否定意图，提取被排除的概念词。
    用于 LLM 不可用时仍能处理"不要X""排除X""与X无关"等表达。
    返回扩展同义词后的排除词列表。
    """
    neg_markers = ["不要", "排除", "除了", "别含", "不含", "无关", "剔除", "去掉"]
    found = query
    for mk in neg_markers:
        idx = query.find(mk)
        if idx >= 0:
            found = query[idx + len(mk):]
            break
    else:
        # 没有否定标记
        if any(k in query for k in ["跟", "和", "与"]) and ("不要" in query or "无关" in query or "不" in query):
            pass
        else:
            return []
    # 从否定标记后截取到句尾/标点，再分词取名词
    import re
    tail = re.split(r"[，。；、,.;！？!?]|的PPT|的页|内容", found)[0]
    if not tail.strip():
        return []
    # 分词取 2 字以上词
    import jieba
    jieba.setLogLevel(60)
    tokens = [w.strip() for w in jieba.lcut(tail) if w.strip()]
    words = [w for w in tokens if len(w) >= 2 and w not in _STOP_WORDS_SKIP]
    return list(dict.fromkeys(words))[:4]
