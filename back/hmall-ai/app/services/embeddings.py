"""Embedding 服务。

硅基流动（SiliconFlow）提供 OpenAI 兼容的 /v1/embeddings 接口，
模型用 BAAI/bge-m3（中文效果好、1024 维，且免费额度够用）。

这里直接用 httpx 发请求，而不是套 LangChain 的 OpenAIEmbeddings：
后者默认会用 tiktoken 把文本转成 token 数组再发，第三方兼容服务大多不认，
踩坑成本比省下的几行代码高。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Embedding 服务不可用（没配 key、网络错误、返回格式异常）。"""


def _endpoint() -> str:
    return f"{settings.siliconflow_base_url.rstrip('/')}/embeddings"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }


async def embed_texts(texts: Sequence[str], *, batch_size: int = 16) -> list[list[float]]:
    """批量向量化。返回的向量顺序与入参严格一致。"""
    if not settings.siliconflow_api_key:
        raise EmbeddingError("未配置 SILICONFLOW_API_KEY，无法生成向量")

    items = [t for t in texts if t is not None]
    if not items:
        return []

    vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=60) as client:
        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            payload = {
                "model": settings.embedding_model,
                "input": batch,
                "encoding_format": "float",
            }
            try:
                resp = await client.post(_endpoint(), headers=_headers(), json=payload)
            except httpx.HTTPError as exc:
                raise EmbeddingError(f"请求 Embedding 服务失败: {exc}") from exc

            if resp.status_code != 200:
                raise EmbeddingError(f"Embedding 接口返回 {resp.status_code}: {resp.text[:300]}")

            data = resp.json().get("data") or []
            # 有的服务不保证返回顺序，按 index 排一下
            data = sorted(data, key=lambda d: d.get("index", 0))
            if len(data) != len(batch):
                raise EmbeddingError(f"Embedding 返回条数不符：期望 {len(batch)}，实际 {len(data)}")
            vectors.extend(d["embedding"] for d in data)

    return vectors


async def embed_query(text: str) -> list[float]:
    """单条查询向量。"""
    vectors = await embed_texts([text])
    if not vectors:
        raise EmbeddingError("Embedding 返回为空")
    return vectors[0]


def embed_texts_sync(texts: Sequence[str], *, batch_size: int = 16) -> list[list[float]]:
    """给离线脚本（ingest.py）和同步代码路径用的版本。"""
    return asyncio.run(embed_texts(texts, batch_size=batch_size))
