"""Agent 与工具的单元测试。

不需要真实大模型密钥：只验证工具定义、未配置密钥时的降级行为、
以及接口返回的统一响应格式。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.order_agent import AgentNotConfigured, build_agent
from app.core.config import settings
from app.tools.order import fetch_latest_order, get_order_status
from main import app


def test_tool_definition() -> None:
    """工具名和入参是模型能看见的契约，改名会直接影响模型调用。"""
    assert get_order_status.name == "get_order_status"
    assert "user_id" in get_order_status.args
    assert "订单" in (get_order_status.description or "")


def test_fetch_latest_order_is_callable() -> None:
    """底层 HTTP 函数可独立测试（不经过 Agent）。"""
    assert callable(fetch_latest_order)


def test_agent_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "")
    with pytest.raises(AgentNotConfigured):
        build_agent(1)


def test_chat_endpoint_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配密钥时应返回 503 + 统一响应格式，而不是 500 堆栈。"""
    monkeypatch.setattr(settings, "llm_api_key", "")
    with TestClient(app) as client:
        resp = client.post("/api/ai/chat", json={"user_id": 1, "message": "我的订单到哪了？"})
    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == 503
    assert "LLM_API_KEY" in body["message"]


def test_chat_endpoint_validation() -> None:
    """缺少 user_id 时返回 422。"""
    with TestClient(app) as client:
        resp = client.post("/api/ai/chat", json={"message": "hi"})
    assert resp.status_code == 422
    assert resp.json()["code"] == 422
