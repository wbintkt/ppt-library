"""Embedding 服务：阿里云百炼 qwen3-vl-embedding（多模态，512 维）

API Key 支持动态配置：优先读数据库 app_settings 表（界面可配，立即生效），
未设置时回退到 .env 的 DASHSCOPE_API_KEY。
"""
import base64
import time
import hashlib

from ..config import settings
from .search_cache import TTLCache

_query_cache = TTLCache(ttl=900)


class EmbeddingError(Exception):
    pass


_api_key_cache = {"key": None, "ts": 0.0}
_CACHE_TTL = 20.0


def _get_api_key() -> str:
    """动态获取 API Key（带缓存）"""
    import time as _t
    now = _t.time()
    if now - _api_key_cache["ts"] < _CACHE_TTL and _api_key_cache["key"] is not None:
        return _api_key_cache["key"]
    key = settings.dashscope_api_key or ""
    try:
        from ..database import SessionLocal
        from ..models import AppSetting
        db = SessionLocal()
        try:
            row = db.query(AppSetting).filter_by(key="DASHSCOPE_API_KEY").first()
            if row and row.value.strip():
                key = row.value.strip()
        finally:
            db.close()
    except Exception:
        pass
    _api_key_cache["key"] = key
    _api_key_cache["ts"] = now
    return key


def _invalidate_key_cache():
    _api_key_cache["key"] = None
    _api_key_cache["ts"] = 0.0


def has_api_key() -> bool:
    return bool(_get_api_key())


def _get_client():
    try:
        from dashscope import MultiModalEmbedding
        return MultiModalEmbedding
    except ImportError:
        raise EmbeddingError("dashscope SDK 未安装")


def _call(input_list: list, retries: int = 3, request_timeout: float | None = None) -> list:
    """调用模型，返回 embedding 列表（与 input 顺序一致）"""
    api_key = _get_api_key()
    if not api_key:
        raise EmbeddingError("未配置 DASHSCOPE_API_KEY")
    MM = _get_client()
    for attempt in range(retries):
        try:
            resp = MM.call(
                model=settings.embed_model,
                input=input_list,
                dimension=settings.embed_dim,
                api_key=api_key,
                **({"request_timeout": request_timeout} if request_timeout is not None else {}),
            )
            if resp.status_code == 200:
                return [e["embedding"] for e in resp.output["embeddings"]]
            err = getattr(resp, "code", "") or ""
            msg = getattr(resp, "message", "") or ""
            if resp.status_code == 429:  # 限流：退避重试
                time.sleep(3 * (attempt + 1))
                continue
            if "InvalidApiKey" in err or "invalid api" in msg.lower():
                raise EmbeddingError(f"API Key 无效: {msg}")
            raise EmbeddingError(f"模型调用失败({resp.status_code}): {msg}")
        except EmbeddingError:
            raise
        except Exception as e:  # 网络等瞬时错误
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise EmbeddingError(f"模型调用异常: {e}")
    raise EmbeddingError("重试次数用尽")


def embed_mixed(inputs: list) -> list:
    """混合输入（text/image 任意组合）-> 向量列表，顺序与 inputs 一致"""
    if not inputs:
        return []
    return _call(inputs)


def embed_texts(texts: list) -> list:
    """文本 -> 向量列表"""
    if not texts:
        return []
    input_list = [{"text": t[:8000]} for t in texts]
    return _call(input_list)


def embed_images(paths: list) -> list:
    """本地图片 -> 向量列表"""
    if not paths:
        return []
    input_list = []
    for p in paths:
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        input_list.append({"image": f"data:image/png;base64,{b64}"})
    return _call(input_list)


def embed_text(text: str) -> list:
    return embed_texts([text])[0]


def embed_query(text: str) -> list:
    """交互查询只调用一次并缓存；批量索引保留原有重试策略。"""
    key = hashlib.sha256(f"{settings.embed_model}|{settings.embed_dim}|{_get_api_key()}|{text}".encode()).hexdigest()
    cached = _query_cache.get(key)
    if cached is not None:
        return cached
    result = _call([{"text": text[:8000]}], retries=1,
                   request_timeout=settings.search_embedding_timeout_seconds)[0]
    _query_cache.put(key, result)
    return result
