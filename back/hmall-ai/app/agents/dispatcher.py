"""Agent 调度：先识别意图，再分给对应的 Agent。

| 意图 | Agent | 工具 |
|---|---|---|
| policy（售后政策） | order_agent | search_policy / get_order_status / request_cancel_order |
| order（订单物流） | order_agent | 同上 |
| shopping（商品导购） | shopping_agent | search_products |
| chitchat（闲聊） | order_agent | 同上（模型通常不会调工具） |

会话记忆是**跨 Agent 共享**的：两个 Agent 用同一个 checkpointer 和 thread_id，
所以用户先说"我的订单到哪了"再说"那帮我推荐个手机壳"，上下文不会断。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from app.agents import order_agent, shopping_agent
from app.agents.intent import Intent, classify_intent

logger = logging.getLogger(__name__)

_AGENTS = {
    Intent.POLICY: order_agent,
    Intent.ORDER: order_agent,
    Intent.SHOPPING: shopping_agent,
    Intent.CHITCHAT: order_agent,
}


def agent_for(intent: Intent) -> Any:
    return _AGENTS[intent]


async def stream_chat(
    user_id: int, message: str, session_id: str
) -> AsyncIterator[dict[str, Any]]:
    """流式：先发一条 intent 事件（前端可以显示"已转给导购助手"），再转发 token。"""
    intent, matched = classify_intent(message)
    logger.info("意图识别 message=%r -> %s（命中 %r）", message, intent.value, matched)

    yield {
        "type": "intent",
        "intent": intent.value,
        "label": intent.label,
        "matched": matched,
    }

    async for event in agent_for(intent).stream_agent(user_id, message, session_id):
        yield event


async def run_chat(
    user_id: int, message: str, session_id: str
) -> tuple[str, list[str], Intent]:
    """非流式：返回 (回答, 调用的工具, 意图)。"""
    intent, matched = classify_intent(message)
    logger.info("意图识别 message=%r -> %s（命中 %r）", message, intent.value, matched)
    reply, tools_used = await agent_for(intent).run_agent(user_id, message, session_id)
    return reply, tools_used, intent
