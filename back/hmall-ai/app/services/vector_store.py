"""向量检索服务：embedding + Milvus 检索 + 知识入库。"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from app.core.config import settings
from app.crud.milvus import MilvusRepository, VectorStoreUnavailable
from app.models.search import SearchHit
from app.services.embeddings import EmbeddingError, embed_texts_sync
from app.utils.text import chunk_text, truncate

logger = logging.getLogger(__name__)

# 查询向量缓存：热门搜索词重复率很高，而 embedding 是一次 ~300ms 的网络往返，
# Milvus 检索本身只要几毫秒。缓存后同一句话的搜索能从 300ms 降到 10ms 级别。
_QUERY_VECTOR_CACHE: dict[str, list[float]] = {}
_QUERY_CACHE_MAX = 2048


class VectorStoreService:
    """把「文本 -> 向量 -> 检索结果」这条链路收口在一个类里。"""

    def __init__(self, repo: MilvusRepository | None = None) -> None:
        self._repo = repo or MilvusRepository()

    # ------------------------------------------------------------- embedding
    def embed(self, texts: list[str]) -> list[list[float]]:
        """统一走硅基流动的 bge-m3（和政策库共用一套 embedding 配置）。

        本方法在 FastAPI 的线程池里被调用（同步端点），所以可以安全地
        用 asyncio.run 包一层。
        """
        try:
            return embed_texts_sync(texts)
        except EmbeddingError as exc:
            raise VectorStoreUnavailable(str(exc)) from exc

    # ----------------------------------------------------------------- 检索
    # 商品库要展示价格/图片/类目，所以显式指定输出字段；
    # 政策库走 services/policy.py 自己的 repo，不受影响。
    ITEM_OUTPUT_FIELDS = ("text", "item_id", "name", "price", "image", "category", "brand", "stock")

    def query_vector(self, query: str) -> list[float]:
        """把查询语句转成向量，带进程内缓存（同样的 query 只算一次）。"""
        key = query.strip()
        cached = _QUERY_VECTOR_CACHE.get(key)
        if cached is not None:
            return cached

        vector = self.embed([key])[0]
        if len(_QUERY_VECTOR_CACHE) >= _QUERY_CACHE_MAX:
            _QUERY_VECTOR_CACHE.clear()
        _QUERY_VECTOR_CACHE[key] = vector
        return vector

    def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        min_score: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        """语义检索。任何一步失败都抛 VectorStoreUnavailable，交给路由降级。"""
        vector = self.query_vector(query)
        expr = self._build_filter_expr(filters or {})
        rows = self._repo.search(
            vector, top_k=top_k, filter_expr=expr, output_fields=self.ITEM_OUTPUT_FIELDS
        )

        hits: list[SearchHit] = []
        for row in rows:
            score = float(row.get("score", 0.0))
            # Milvus 的 COSINE 距离返回的是相似度，越大越相关
            if score < min_score:
                continue
            hits.append(
                SearchHit(
                    item_id=str(row.get("item_id") or row.get("id") or ""),
                    name=row.get("name"),
                    score=round(score, 4),
                    snippet=truncate(row.get("text"), 160),
                    metadata=self._item_metadata(row),
                )
            )
        return hits

    @staticmethod
    def _item_metadata(row: dict[str, Any]) -> dict[str, Any]:
        """挑出前端渲染商品卡片需要的字段，空值不返回，省带宽。"""
        keys = ("price", "image", "category", "brand", "stock")
        return {k: row[k] for k in keys if row.get(k) not in (None, "", 0)}

    # ----------------------------------------------------------------- 写入
    def ingest(
        self,
        documents: Iterable[dict[str, Any]],
        *,
        chunk_size: int = 400,
        overlap: int = 50,
    ) -> int:
        """把 [{'item_id':..., 'name':..., 'text':...}] 切块、向量化后写入 Milvus。"""
        records: list[dict[str, Any]] = []
        for doc in documents:
            text = str(doc.get("text") or "").strip()
            if not text:
                continue
            for chunk in chunk_text(text, chunk_size=chunk_size, overlap=overlap):
                records.append(
                    {
                        "item_id": str(doc.get("item_id", "")),
                        "name": doc.get("name"),
                        "text": chunk,
                        "vector": None,  # 占位，下面统一填
                    }
                )
        if not records:
            return 0

        vectors = self.embed([r["text"] for r in records])
        for record, vector in zip(records, vectors):
            record["vector"] = vector

        self._repo.ensure_collection(len(vectors[0]))
        return self._repo.upsert(records)

    # ----------------------------------------------------------------- 辅助
    @staticmethod
    def _build_filter_expr(filters: dict[str, Any]) -> str:
        """把 {'brand': '华为'} 拼成 Milvus 的过滤表达式（只做等值，防注入用白名单字符）。"""
        parts: list[str] = []
        for key, value in filters.items():
            if not str(key).replace("_", "").isalnum():
                continue
            if isinstance(value, (int, float)):
                parts.append(f"{key} == {value}")
            else:
                safe = str(value).replace('"', '\\"')
                parts.append(f'{key} == "{safe}"')
        return " and ".join(parts)


vector_store_service = VectorStoreService()
