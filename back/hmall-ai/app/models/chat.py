"""对话相关模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """一轮历史消息。"""

    role: Literal["system", "user", "assistant"] = Field(description="角色")
    content: str = Field(description="内容")


class Reference(BaseModel):
    """回答引用的商品/知识片段，方便前端做“来源卡片”。"""

    item_id: str | None = Field(default=None, description="商品 id")
    name: str | None = Field(default=None, description="商品名称")
    score: float = Field(default=0.0, description="相关度，0~1")
    snippet: str | None = Field(default=None, description="命中的文本片段")


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="用户问题", examples=["这款手机保修多久？"])
    session_id: str | None = Field(default=None, description="会话 id，不传则新建")
    history: list[ChatMessage] = Field(default_factory=list, description="历史对话，最多取最近 10 条")
    top_k: int = Field(default=4, ge=1, le=20, description="检索多少条知识作为上下文")
    item_id: str | None = Field(default=None, description="针对某个商品提问时传商品 id")


class ChatResponse(BaseModel):
    session_id: str = Field(description="会话 id")
    answer: str = Field(description="模型回答")
    references: list[Reference] = Field(default_factory=list, description="引用的知识/商品")
    degraded: bool = Field(default=False, description="true 表示未配置大模型或检索失败，返回的是兜底话术")
