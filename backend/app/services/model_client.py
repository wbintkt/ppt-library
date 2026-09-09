"""交互检索的单次 HTTP 请求：硬性总时限、取消后释放连接、不自动重试。"""
import asyncio
import httpx
from ..config import settings


async def post_json(path: str, payload: dict, api_key: str, timeout: float) -> dict:
    async def request():
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                settings.search_model_api_base.rstrip('/') + path,
                headers={'Authorization': 'Bearer ' + api_key}, json=payload,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError('invalid provider response')
            return data
    return await asyncio.wait_for(request(), timeout=timeout)
