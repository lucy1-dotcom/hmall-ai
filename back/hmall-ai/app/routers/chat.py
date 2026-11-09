"""智能客服对话接口。"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter

from app.core.exceptions import AppException
from app.crud.milvus import VectorStoreUnavailable
from app.models.chat import ChatRequest, ChatResponse, Reference
from app.services.item_client import item_client
from app.services.llm import llm_service
from app.services.vector_store import vector_store_service
from app.utils.text import join_context

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["智能客服"])


@router.post("", response_model=ChatResponse, summary="智能客服对话")
def chat(req: ChatRequest) -> ChatResponse:
    """RAG 问答：先检索知识，再把上下文交给大模型。

    检索失败不会让接口报错，而是退化成本轮无上下文的回答，并在
    degraded=true 里告诉调用方。
    """
    session_id = req.session_id or uuid.uuid4().hex
    references: list[Reference] = []
    context_parts: list[str] = []
    degraded = False

    # 1. 检索知识库（商品知识 / 常见问题）
    try:
        hits = vector_store_service.search(req.question, top_k=req.top_k)
        for hit in hits:
            references.append(
                Reference(item_id=hit.item_id, name=hit.name, score=hit.score, snippet=hit.snippet)
            )
            if hit.snippet:
                context_parts.append(hit.snippet)
    except VectorStoreUnavailable as exc:
        logger.warning("向量检索不可用，本轮不带知识上下文: %s", exc)

    # 2. 如果指定了商品，把商品信息补进上下文（走网关查 Java 服务）
    if req.item_id:
        item = item_client.get_item(req.item_id)
        if item:
            context_parts.append(
                "商品：{name}；价格：{price} 分；库存：{stock}；品牌：{brand}".format(
                    name=item.get("name"),
                    price=item.get("price"),
                    stock=item.get("stock"),
                    brand=item.get("brand"),
                )
            )
            references.append(
                Reference(item_id=str(item.get("id")), name=item.get("name"), score=1.0)
            )

    # 3. 调用大模型
    try:
        answer, llm_degraded = llm_service.chat(
            req.question, context=join_context(context_parts), history=req.history
        )
    except Exception as exc:  # noqa: BLE001 - 上游模型异常统一转 502
        logger.exception("调用大模型失败")
        raise AppException("大模型服务调用失败，请稍后重试", code=502, detail=str(exc)) from exc

    return ChatResponse(
        session_id=session_id,
        answer=answer,
        references=references,
        degraded=degraded or llm_degraded,
    )
