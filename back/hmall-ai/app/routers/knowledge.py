"""知识库写入接口（后台/离线任务用）。"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from fastapi import APIRouter

from app.core.exceptions import AppException
from app.crud.milvus import VectorStoreUnavailable
from app.services.vector_store import vector_store_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge", tags=["知识库"])


class KnowledgeDoc(BaseModel):
    item_id: str = Field(description="商品 id，用于回溯")
    name: str | None = Field(default=None, description="商品名")
    text: str = Field(min_length=1, description="待向量化的文本，如商品描述 + 参数")


class IngestRequest(BaseModel):
    documents: list[KnowledgeDoc] = Field(default_factory=list, description="待写入的文档")
    chunk_size: int = Field(default=400, ge=100, le=2000, description="切块大小（字符）")
    overlap: int = Field(default=50, ge=0, le=200, description="块间重叠")


class IngestResponse(BaseModel):
    written: int = Field(description="写入的向量条数")
    message: str = "ok"


@router.post("/ingest", response_model=IngestResponse, summary="写入/更新知识向量")
def ingest(req: IngestRequest) -> IngestResponse:
    if not req.documents:
        raise AppException("documents 不能为空")
    try:
        written = vector_store_service.ingest(
            [doc.model_dump() for doc in req.documents],
            chunk_size=req.chunk_size,
            overlap=req.overlap,
        )
    except VectorStoreUnavailable as exc:
        raise AppException("向量库不可用，写入失败", code=503, detail=str(exc)) from exc
    return IngestResponse(written=written, message=f"已写入 {written} 条向量")
