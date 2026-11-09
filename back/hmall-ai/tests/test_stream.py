"""流式接口（SSE）的单元测试。

不依赖真实模型：把 stream_agent 换成一个假的异步生成器，
只验证「SSE 报文格式」和「错误能否作为事件推给前端」。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from main import app


def _events(resp_text: str) -> list[str]:
    return [block.strip() for block in resp_text.split("\n\n") if block.strip()]


def test_stream_returns_sse_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "sk-test")

    async def fake_stream(user_id: int, message: str, session_id: str):
        yield {"type": "tool", "name": "search_policy"}
        yield {"type": "token", "content": "你"}
        yield {"type": "token", "content": "好"}

    monkeypatch.setattr("app.routers.agent.stream_agent", fake_stream)

    with TestClient(app) as client:
        resp = client.post("/api/ai/chat", json={"user_id": 1, "message": "hi", "session_id": "s1"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _events(resp.text)
    assert events[0].startswith("data:") and '"meta"' in events[0]
    assert any('"type": "tool"' in e for e in events)
    assert sum(1 for e in events if '"type": "token"' in e) == 2
    assert '"done"' in events[-1]


def test_stream_emits_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """流已经开始后出错，不能再改 HTTP 状态码，只能用 error 事件告知。"""
    monkeypatch.setattr(settings, "llm_api_key", "sk-test")

    async def boom(user_id: int, message: str, session_id: str):
        yield {"type": "token", "content": "半"}
        raise RuntimeError("模型超时")

    monkeypatch.setattr("app.routers.agent.stream_agent", boom)

    with TestClient(app) as client:
        resp = client.post("/api/ai/chat", json={"user_id": 1, "message": "hi"})

    assert resp.status_code == 200
    events = _events(resp.text)
    assert any('"type": "error"' in e and "模型超时" in e for e in events)


def test_stream_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配密钥时，推流前就返回 503 JSON。"""
    monkeypatch.setattr(settings, "llm_api_key", "")
    with TestClient(app) as client:
        resp = client.post("/api/ai/chat", json={"user_id": 1, "message": "hi"})
    assert resp.status_code == 503
    assert resp.json()["code"] == 503
