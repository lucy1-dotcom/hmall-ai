"""测试：健康检查与 CORS 预检。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_health() -> None:
    with TestClient(app) as client:
        resp = client.get("/ai/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "UP"
    assert body["service"] == "hmall-ai"
    assert "llm" in body["components"]


def test_ping() -> None:
    with TestClient(app) as client:
        resp = client.get("/ai/ping")
    assert resp.status_code == 200
    assert resp.json()["message"] == "pong"


def test_cors_preflight() -> None:
    """前端 18080 跨域调 8087，预检必须放行。"""
    headers = {
        "Origin": "http://localhost:18080",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    with TestClient(app) as client:
        resp = client.options("/ai/chat", headers=headers)
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") in {"*", "http://localhost:18080"}


def test_search_request_validation() -> None:
    """参数校验失败要返回 422 且结构统一。"""
    with TestClient(app) as client:
        resp = client.post("/ai/search", json={"query": ""})
    assert resp.status_code == 422
    assert resp.json()["code"] == 422
