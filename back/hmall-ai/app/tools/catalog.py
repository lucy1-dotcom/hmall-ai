"""商品检索工具：给导购 Agent 用的语义搜索。

走的是 Milvus（hmall_items），和 `/ai/search` 接口共用同一套检索逻辑，
区别只是这里把结果压缩成适合塞进 prompt 的 JSON，省 token。
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from app.services.vector_store import vector_store_service

logger = logging.getLogger(__name__)


@tool
def search_products(query: str, top_k: str = "5") -> str:
    """按用户的自然语言描述检索在售商品（语义检索，不是关键词匹配）。

    什么时候用：用户想买什么东西、让你推荐商品、问"有没有……"、
    "哪个适合……"、"帮我挑一个……"这类导购需求时调用。

    参数 query：把用户需求改写成一句商品描述，例如
      "适合送礼的女式钱包"、"打游戏用的手机"，保留关键属性，不要带客套话。
    参数 top_k：返回几条，默认 5，最多 10。

    返回 JSON 数组，字段：itemId / name / price（单位：分）/ category / brand / score。

    注意：这里刻意写成**同步**函数。`vector_store_service.search` 内部的 embedding
    用的是 `asyncio.run`，如果在 async 工具里直接调用会抛
    "asyncio.run() cannot be called from a running event loop"；
    LangChain 会把同步工具丢到线程池执行，正好避开这个冲突。
    """
    try:
        limit = max(1, min(int(top_k or 5), 10))
    except (TypeError, ValueError):
        limit = 5

    try:
        hits = vector_store_service.search(query, top_k=limit)
    except Exception as exc:  # noqa: BLE001 - 向量库不可用时要给模型一个可读的失败信息
        logger.warning("商品检索失败 query=%r err=%s", query, exc)
        return f"商品检索服务暂不可用：{exc}"

    if not hits:
        return "没有检索到相关商品。"

    payload = [
        {
            "itemId": hit.item_id,
            "name": hit.name,
            "price": hit.metadata.get("price"),
            "category": hit.metadata.get("category"),
            "brand": hit.metadata.get("brand"),
            "score": hit.score,
        }
        for hit in hits
    ]
    logger.info("商品检索 query=%r 命中 %d 条", query, len(payload))
    return json.dumps(payload, ensure_ascii=False)
