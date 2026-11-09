"""政策知识库（RAG）相关测试。

不需要真实硅基流动密钥，也不需要 Milvus 在跑：
只验证切块规则、工具注册、以及没配密钥时的降级提示。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.order_agent import AGENT_TOOLS
from app.core.config import settings
from app.tools.policy import search_policy
from app.utils.text import chunk_text
from main import app


def test_policy_chunking_respects_size() -> None:
    """切块大小要可预期，且不能把内容切丢。"""
    text = "第一条 规则说明。" * 200
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 520 for c in chunks)
    # 重叠会让总长度略大于原文，但不应丢失内容
    assert sum(len(c) for c in chunks) >= len(text)


def test_agents_have_two_tools() -> None:
    """订单、政策两个工具都要挂在 Agent 上。"""
    names = [tool.name for tool in AGENT_TOOLS]
    assert names == ["get_order_status", "search_policy"]


def test_search_policy_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配 SILICONFLOW_API_KEY 时给出明确提示，而不是抛异常。"""
    import asyncio

    monkeypatch.setattr(settings, "siliconflow_api_key", "")
    result = asyncio.run(search_policy.ainvoke({"query": "拆封的手机能退吗"}))
    assert "SILICONFLOW_API_KEY" in result


def test_chat_endpoint_validation_still_works() -> None:
    """/api/ai/chat 的参数校验不受新工具影响。"""
    with TestClient(app) as client:
        resp = client.post("/api/ai/chat", json={"user_id": 0, "message": "hi"})
    assert resp.status_code == 422
