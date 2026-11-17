"""待确认动作（Human-in-the-loop）。

**为什么不让模型直接执行写操作**

用户说「帮我把最近那单取消了吧」，模型要做的是：
1. 判断这是写操作；
2. 生成一个**待确认动作**（落库 + 短 TTL），把 actionId 和一句话摘要返回给前端；
3. 用户点「确认」之后，才真正调用 Java 的取消订单接口。

这样做有三个好处：
- **防误操作**：模型可能听错订单号，也可能用户只是随便问问；
- **可审计**：每次写操作都有一条记录（谁、什么时候、什么参数、结果如何）；
- **可幂等**：重复点确认不会重复执行（状态机 + 条件更新双重保证）。

存储用 SQLite：动作数据量很小，不值得引入 Redis；而且它和会话记忆在同一个
data/ 目录，运维上是一个东西。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class ActionExecutionError(RuntimeError):
    """动作执行失败（调 Java 接口失败、状态不允许等）。"""


@dataclass
class PendingAction:
    id: str
    user_id: int
    action_type: str
    params: dict[str, Any]
    summary: str
    status: str  # pending / executing / done / failed / cancelled / expired
    created_at: float
    expires_at: float
    result: dict[str, Any] = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        return self.status == "pending" and time.time() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "actionId": self.id,
            "type": self.action_type,
            "params": self.params,
            "summary": self.summary,
            "status": self.status,
            "expiresIn": max(0, int(self.expires_at - time.time())),
            "result": self.result,
        }


class ActionStore:
    """待确认动作的持久化 + 状态机。"""

    def __init__(self, path: str | None = None, ttl: int | None = None) -> None:
        self.path = path or settings.actions_db_path
        self.ttl = ttl if ttl is not None else settings.action_ttl_seconds
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------- 内部工具
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_action (
                    id          TEXT PRIMARY KEY,
                    user_id     INTEGER NOT NULL,
                    type        TEXT NOT NULL,
                    params      TEXT NOT NULL,
                    summary     TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    created_at  REAL NOT NULL,
                    expires_at  REAL NOT NULL,
                    result      TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_action_user ON pending_action(user_id)")

    @staticmethod
    def _row_to_action(row: sqlite3.Row) -> PendingAction:
        return PendingAction(
            id=row["id"],
            user_id=row["user_id"],
            action_type=row["type"],
            params=json.loads(row["params"] or "{}"),
            summary=row["summary"],
            status=row["status"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            result=json.loads(row["result"] or "{}"),
        )

    # ---------------------------------------------------------------- 对外
    def create(
        self,
        user_id: int,
        action_type: str,
        params: dict[str, Any],
        summary: str,
    ) -> PendingAction:
        now = time.time()
        action = PendingAction(
            id="act_" + uuid.uuid4().hex[:16],
            user_id=int(user_id),
            action_type=action_type,
            params=params,
            summary=summary,
            status="pending",
            created_at=now,
            expires_at=now + self.ttl,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO pending_action (id,user_id,type,params,summary,status,created_at,expires_at,result)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    action.id,
                    action.user_id,
                    action.action_type,
                    json.dumps(action.params, ensure_ascii=False),
                    action.summary,
                    action.status,
                    action.created_at,
                    action.expires_at,
                    "{}",
                ),
            )
        logger.info("生成待确认动作 %s type=%s user=%s", action.id, action_type, user_id)
        return action

    def get(self, action_id: str) -> PendingAction | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM pending_action WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            return None
        action = self._row_to_action(row)
        if action.expired:
            self.mark(action.id, "expired")
            action.status = "expired"
        return action

    def mark(self, action_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE pending_action SET status = ?, result = COALESCE(?, result) WHERE id = ?",
                (status, json.dumps(result, ensure_ascii=False) if result is not None else None, action_id),
            )


action_store = ActionStore()


# ---------------------------------------------------------------------------
# 执行器：按动作类型调对应的 Java 接口
# ---------------------------------------------------------------------------
async def _cancel_order(action: PendingAction) -> dict[str, Any]:
    order_id = action.params.get("orderId")
    if not order_id:
        raise ActionExecutionError("待确认动作里缺少 orderId")

    url = f"{settings.hmall_gateway_url.rstrip('/')}/api/order/{order_id}/cancel"
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
            resp = await client.put(url, params={"userId": action.user_id})
    except httpx.HTTPError as exc:
        raise ActionExecutionError(f"调用订单服务失败: {exc}") from exc

    if resp.status_code == 403:
        raise ActionExecutionError("无权操作该订单（订单不属于当前用户）")
    if resp.status_code >= 400:
        raise ActionExecutionError(f"订单服务返回 {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if not data.get("cancelled"):
        raise ActionExecutionError(str(data.get("message") or "订单当前状态不允许取消"))
    return data


_EXECUTORS = {
    "cancel_order": _cancel_order,
}


async def execute_action(action: PendingAction) -> dict[str, Any]:
    """执行已经确认的动作。"""
    executor = _EXECUTORS.get(action.action_type)
    if executor is None:
        raise ActionExecutionError(f"不支持的动作类型: {action.action_type}")
    return await executor(action)
