"""待确认动作（Human-in-the-loop）的单元测试。

覆盖：
1. 状态机：pending -> done / cancelled / expired
2. 执行器：按类型分发、调 Java 接口的 URL 和参数正确、失败要抛 ActionExecutionError
3. 工具：生成的是「待确认动作」，而不是直接执行
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.services import actions as actions_module
from app.services.actions import ActionExecutionError, ActionStore, execute_action


def make_store(tmp_path, ttl: int = 60) -> ActionStore:
    return ActionStore(path=str(tmp_path / "actions.db"), ttl=ttl)


def test_create_and_get_pending_action(tmp_path):
    store = make_store(tmp_path)

    action = store.create(1, "cancel_order", {"orderId": "100"}, "取消订单 100")

    loaded = store.get(action.id)
    assert loaded is not None
    assert loaded.status == "pending"
    assert loaded.user_id == 1
    assert loaded.params["orderId"] == "100"
    assert loaded.summary == "取消订单 100"


def test_mark_done_persists_result(tmp_path):
    store = make_store(tmp_path)
    action = store.create(1, "cancel_order", {"orderId": "100"}, "取消订单 100")

    store.mark(action.id, "done", {"orderId": 100, "cancelled": True})

    loaded = store.get(action.id)
    assert loaded.status == "done"
    assert loaded.result["cancelled"] is True


def test_expired_action_is_marked(tmp_path):
    store = make_store(tmp_path, ttl=-1)  # 创建即过期
    action = store.create(1, "cancel_order", {"orderId": "100"}, "取消订单 100")

    loaded = store.get(action.id)

    assert loaded.status == "expired"


def test_get_unknown_action_returns_none(tmp_path):
    assert make_store(tmp_path).get("act_not_exist") is None


def test_execute_unknown_type_raises(tmp_path):
    store = make_store(tmp_path)
    action = store.create(1, "unknown_op", {}, "未知动作")

    with pytest.raises(ActionExecutionError):
        asyncio.run(execute_action(action))


def test_cancel_order_calls_java_with_user_and_order(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    action = store.create(1, "cancel_order", {"orderId": "2083047037284134914"}, "取消订单")

    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"orderId": 2083047037284134914, "cancelled": True, "message": "订单已取消，库存已回补"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def put(self, url, params=None):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr(actions_module.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(execute_action(action))

    assert result["cancelled"] is True
    assert captured["url"].endswith("/api/order/2083047037284134914/cancel")
    assert captured["params"] == {"userId": 1}


def test_cancel_order_failure_raises(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    action = store.create(1, "cancel_order", {"orderId": "100"}, "取消订单")

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            # Java 侧说"当前状态不允许取消"
            return {"orderId": 100, "cancelled": False, "message": "订单当前状态不允许取消（可能已支付或已关闭）"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def put(self, url, params=None):
            return FakeResponse()

    monkeypatch.setattr(actions_module.httpx, "AsyncClient", FakeClient)

    with pytest.raises(ActionExecutionError):
        asyncio.run(execute_action(action))


def test_request_cancel_order_tool_creates_pending_action(tmp_path, monkeypatch):
    """工具只生成待确认动作，返回值里要有 actionId，且此时不该有任何执行。"""
    from app.tools import order as order_tool

    store = make_store(tmp_path)
    monkeypatch.setattr(order_tool, "action_store", store)

    raw = asyncio.run(
        order_tool.request_cancel_order.ainvoke({"user_id": "1", "order_id": "2083047037284134914"})
    )
    payload = json.loads(raw)

    assert payload["status"] == "pending_confirmation"
    assert payload["actionId"].startswith("act_")
    assert "2083047037284134914" in payload["summary"]
    assert store.get(payload["actionId"]).status == "pending"
