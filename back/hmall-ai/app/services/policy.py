"""政策知识库检索（RAG 的 Retrieval 部分）。

支持三种检索策略，用 ``POLICY_RETRIEVAL_MODE`` 切换：

| 模式 | 说明 |
|---|---|
| `vector` | 纯向量检索（Milvus ANN），语义好但漏关键词 |
| `hybrid` | 向量 + BM25 双路召回，RRF 融合 |
| `hybrid_rerank`（默认） | 融合后再用 bge-reranker 精排 |

后面两种的价值见 ``perf/rag_eval.py`` 的评测结果：
纯向量在"条款编号/数字/专有名词"类问题上容易漏，
BM25 补上字面命中，rerank 再把真正回答问题的块顶到第一。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.crud.milvus import MilvusRepository
from app.services.embeddings import embed_query
from app.services.retrieval import BM25Index, RerankError, rerank, rrf_fuse

logger = logging.getLogger(__name__)

_POLICY_FIELDS = ("text", "source", "chunk_index")


class PolicyStore:
    """把「问题 -> 向量 -> Milvus 检索」收口在一起。"""

    def __init__(self) -> None:
        self._repo = MilvusRepository(settings.policy_collection)
        self._chunks: list[dict[str, Any]] = []
        self._bm25: BM25Index | None = None

    @property
    def collection(self) -> str:
        return settings.policy_collection

    # ------------------------------------------------------------ BM25 索引
    def _ensure_bm25(self) -> None:
        """懒加载：首次需要 BM25 时才把整库拉出来建索引（知识库很小）。"""
        if self._bm25 is not None and self._chunks:
            return
        rows = self._repo.query_all()
        if not rows:
            self._chunks = []
            self._bm25 = BM25Index([])
            return
        self._chunks = rows
        self._bm25 = BM25Index([str(r.get("text") or "") for r in rows])
        logger.info("BM25 索引已构建：%d 块", len(rows))

    def refresh(self) -> None:
        """重新灌库后调用，丢掉旧的 BM25 索引缓存。"""
        self._chunks = []
        self._bm25 = None

    # ---------------------------------------------------------------- 检索
    async def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """返回命中的条款，按相关度从高到低。

        四种模式（``POLICY_RETRIEVAL_MODE``）：
        - ``vector``：纯向量
        - ``vector_rerank``：向量召回后直接精排
        - ``hybrid``：向量 + BM25 加权 RRF 融合
        - ``hybrid_rerank``：融合后再精排（默认）
        """
        limit = top_k or settings.policy_top_k
        mode = (settings.policy_retrieval_mode or "vector").lower()
        candidates = max(settings.policy_candidate_k, limit)

        vector = await embed_query(query)
        # pymilvus 的客户端是同步的，丢到线程池，避免阻塞事件循环
        rows = await asyncio.to_thread(
            self._repo.search, vector, candidates, output_fields=_POLICY_FIELDS
        )
        rows = [dict(r) for r in rows]

        if mode == "vector":
            logger.info("政策检索(mode=vector) query=%r 命中 %d 条", query, len(rows))
            return rows[:limit]

        pool = rows
        if mode.startswith("hybrid"):
            pool = await self._hybrid_fuse(query, rows, candidates)

        if not mode.endswith("_rerank") or not settings.rerank_enabled:
            logger.info("政策检索(mode=%s) query=%r 候选 %d 条", mode, query, len(pool))
            return pool[:limit]

        # ---------------------------------------------------------- 精排
        try:
            pairs = await rerank(query, [str(r.get("text") or "") for r in pool], top_n=limit)
        except RerankError as exc:
            logger.warning("rerank 失败，降级为召回顺序: %s", exc)
            return pool[:limit]

        reranked = [
            {**pool[idx], "score": round(score, 4)}
            for idx, score in pairs
            if 0 <= idx < len(pool)
        ]
        logger.info(
            "政策检索(mode=%s) query=%r 候选 %d 条 -> 重排取 %d 条",
            mode, query, len(pool), len(reranked),
        )
        return reranked[:limit] or pool[:limit]

    async def _hybrid_fuse(
        self, query: str, vector_rows: list[dict[str, Any]], candidates: int
    ) -> list[dict[str, Any]]:
        """向量 + BM25 双路召回，按加权 RRF 融合。"""
        await asyncio.to_thread(self._ensure_bm25)
        assert self._bm25 is not None
        bm25_hits = self._bm25.search(query, candidates)
        # BM25 过滤：中文 bigram 在短块上噪声很大，只保留不低于最高分 50% 的命中，
        # 且最多 5 条。不过滤的话弱相关块会把向量召回的正确答案挤下去。
        if bm25_hits:
            best = bm25_hits[0][1]
            bm25_hits = [(i, s) for i, s in bm25_hits if s >= best * 0.5][:5]
        bm25_rows = [dict(self._chunks[i], score=round(s, 4)) for i, s in bm25_hits]

        by_id: dict[str, dict[str, Any]] = {str(r.get("id")): r for r in vector_rows}
        for row in bm25_rows:
            by_id.setdefault(str(row.get("id")), row)

        fused = rrf_fuse(
            [[str(r.get("id")) for r in vector_rows], [str(r.get("id")) for r in bm25_rows]],
            top_k=candidates,
            weights=[1.0, settings.policy_bm25_weight],
        )
        logger.info(
            "混合召回 query=%r 向量 %d 条 / BM25 %d 条 -> 融合 %d 条",
            query, len(vector_rows), len(bm25_rows), len(fused),
        )
        return [{**by_id[doc_id], "score": round(score, 4)} for doc_id, score in fused if doc_id in by_id]


policy_store = PolicyStore()
