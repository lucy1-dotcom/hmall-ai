"""语义搜索接口：向量检索优先，失败时降级为关键词搜索。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.crud.milvus import VectorStoreUnavailable
from app.models.search import SearchHit, SearchRequest, SearchResponse
from app.services.item_client import item_client
from app.services.vector_store import vector_store_service
from app.utils.text import truncate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["语义搜索"])


@router.post("", response_model=SearchResponse, summary="自然语言搜索商品")
def search(req: SearchRequest) -> SearchResponse:
    """先走 Milvus 语义检索；向量库不可用时退回商品服务的关键词搜索。

    降级是显式的：response.degraded=true，前端可以据此提示“当前为关键词搜索”。
    """
    try:
        hits = vector_store_service.search(
            req.query, top_k=req.top_k, min_score=req.min_score, filters=req.filters
        )
        return SearchResponse(query=req.query, total=len(hits), hits=hits)
    except VectorStoreUnavailable as exc:
        logger.warning("向量检索不可用，降级为关键词搜索: %s", exc)

    try:
        items = item_client.search_items(req.query, size=req.top_k)
        hits = [
            SearchHit(
                item_id=str(item.get("id")),
                name=item.get("name"),
                score=0.0,
                snippet=truncate(item.get("name"), 80),
                metadata={k: item.get(k) for k in ("price", "brand", "category", "image") if item.get(k) is not None},
            )
            for item in items
        ]
        return SearchResponse(
            query=req.query,
            total=len(hits),
            hits=hits,
            degraded=True,
            message="向量检索不可用，已降级为关键词搜索",
        )
    except Exception as exc:  # noqa: BLE001 - 网关也不可用时给空结果而不是 500
        logger.warning("关键词搜索也失败: %s", exc)
        return SearchResponse(
            query=req.query,
            total=0,
            hits=[],
            degraded=True,
            message=f"检索服务暂不可用: {exc}",
        )
