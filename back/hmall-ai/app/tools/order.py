"""Agent 可调用的工具（Tool）。

每个工具都是一个普通函数 + @tool 装饰器：
- 函数签名 -> 模型看到的参数
- docstring -> 模型看到的工具描述（写得越清楚，模型越会用）
- 返回值必须是字符串（LangChain 会把它作为 ToolMessage 塞回对话）

这里用 httpx 异步请求 Java 后端，不阻塞事件循环。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from langchain_core.tools import tool

from app.core.config import settings
from app.services.actions import action_store

logger = logging.getLogger(__name__)


def _order_url() -> str:
    """订单接口地址，主机部分来自环境变量 HMALL_GATEWAY_URL。"""
    return f"{settings.hmall_gateway_url.rstrip('/')}{settings.order_latest_path}"


async def fetch_latest_order(user_id: str | int) -> dict[str, Any]:
    """直接请求 Java 接口，返回原始 JSON。

    抽成独立函数是为了在测试里绕过 Agent，单独验证这条 HTTP 链路。
    """
    url = _order_url()
    params = {"userId": str(user_id)}
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    logger.info("查询订单成功 user_id=%s url=%s resp=%s", user_id, url, data)
    return data


@tool
async def get_order_status(user_id: str) -> str:
    """查询指定用户最近一笔订单的订单号和当前状态。

    什么时候用：用户问「我的订单到哪了」「发货了吗」「最近买了什么」这类问题时调用。
    参数 user_id：当前登录用户的 id，必须原样使用系统提示里给出的那个数字，不要自己编。
    """
    try:
        data = await fetch_latest_order(user_id)
    except httpx.HTTPStatusError as exc:
        logger.warning("订单接口返回错误状态 user_id=%s status=%s", user_id, exc.response.status_code)
        return f"查询订单失败：订单服务返回 {exc.response.status_code}"
    except httpx.HTTPError as exc:
        logger.warning("订单接口调用失败 user_id=%s err=%s", user_id, exc)
        return f"查询订单失败：{exc}"

    order_id = data.get("orderId")
    if not order_id:
        return "该用户当前没有任何订单。"

    # 返回 JSON 字符串比自然语言更省 token，也方便模型准确引用字段
    return json.dumps(
        {
            "orderId": order_id,
            "status": data.get("status"),
            "totalFee": data.get("totalFee"),
            "createTime": data.get("createTime"),
        },
        ensure_ascii=False,
    )


@tool
async def request_cancel_order(user_id: str, order_id: str) -> str:
    """为当前用户创建一条「取消订单」的待确认动作（**不会立即执行**）。

    什么时候用：用户**明确要求**取消/撤销订单时（例如「帮我把订单取消了」）。
    什么时候别用：用户只是问「能不能取消」「取消会怎样」——那是在咨询，直接按政策回答。

    使用规则：
    1. 必须传真实订单号，不能编造；不确定就先调 get_order_status 查最近一笔。
    2. 调用后订单**并不会被取消**，只是生成了一个待确认动作，
       你要把 summary 告诉用户，并提示他「在页面上点击确认后才会真正执行」。
    3. 绝不要对用户说「已经帮您取消了」——执行与否由用户在确认接口里决定。

    参数 user_id：当前登录用户 id，原样使用系统提示里给出的数字。
    参数 order_id：要取消的订单号。
    """
    try:
        action = action_store.create(
            user_id=int(user_id),
            action_type="cancel_order",
            params={"orderId": str(order_id)},
            summary=f"取消订单 {order_id}（取消后库存会回补，且不可撤销）",
        )
    except (TypeError, ValueError):
        return "生成待确认动作失败：user_id 必须是数字"

    return json.dumps(
        {
            "actionId": action.id,
            "status": "pending_confirmation",
            "summary": action.summary,
            "expiresIn": max(0, int(action.expires_at - time.time())),
            "nextStep": "等待用户在前端确认；确认接口为 POST /ai/actions/{actionId}/confirm",
        },
        ensure_ascii=False,
    )
