"""语义搜索相关模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="自然语言查询", examples=["适合打游戏的手机"])
    top_k: int = Field(default=10, ge=1, le=50, description="返回条数")
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, description="最低相关度，低于该值丢弃")
    filters: dict[str, Any] = Field(default_factory=dict, description="元数据过滤，如 {brand: 华为}")


class SearchHit(BaseModel):
    item_id: str = Field(description="商品 id")
    name: str | None = Field(default=None, description="商品名称")
    score: float = Field(default=0.0, description="相关度 0~1")
    snippet: str | None = Field(default=None, description="命中的内容片段")
    metadata: dict[str, Any] = Field(default_factory=dict, description="其它元数据")


class SearchResponse(BaseModel):
    query: str
    total: int = Field(description="命中的条数")
    hits: list[SearchHit] = Field(default_factory=list)
    degraded: bool = Field(default=False, description="true 表示向量检索不可用，已降级为关键词搜索")
    message: str | None = Field(default=None, description="降级原因等提示")
