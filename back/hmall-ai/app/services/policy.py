"""政策知识库检索（RAG 的 Retrieval 部分）。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.crud.milvus import MilvusRepository
from app.services.embeddings import embed_query

logger = logging.getLogger(__name__)


class PolicyStore:
    """把「问题 -> 向量 -> Milvus 检索」收口在一起。"""

    def __init__(self) -> None:
        self._repo = MilvusRepository(settings.policy_collection)

    @property
    def collection(self) -> str:
        return settings.policy_collection

    async def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """返回命中的条款，按相似度从高到低。"""
        vector = await embed_query(query)
        limit = top_k or settings.policy_top_k
        # pymilvus 的客户端是同步的，丢到线程池，避免阻塞事件循环
        rows = await asyncio.to_thread(
            self._repo.search,
            vector,
            limit,
            output_fields=("text", "source", "chunk_index"),
        )
        logger.info("政策检索 query=%r 命中 %d 条", query, len(rows))
        return rows


policy_store = PolicyStore()
