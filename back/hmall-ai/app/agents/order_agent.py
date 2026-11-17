"""售后 Agent：订单查询 + 政策 RAG + 取消订单（写操作）。

只负责「售后 / 订单」类问题，商品导购由 shopping_agent 负责，
入口处用 intent.classify_intent 做分流（见 agents/dispatcher.py）。
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from app.agents import base
from app.tools.order import get_order_status, request_cancel_order
from app.tools.policy import search_policy

# 兼容旧引用：外部一直是从本模块 import 这几个名字
AgentNotConfigured = base.AgentNotConfigured
MAX_HISTORY_MESSAGES = base.MAX_HISTORY_MESSAGES
thread_config = base.thread_config

# 工具集中在一处，便于测试断言和后续扩展
AGENT_TOOLS = [get_order_status, search_policy, request_cancel_order]

SYSTEM_PROMPT = """你是黑马商城（hmall）的售后服务助手，说话简洁、礼貌，用中文回答。

当前登录用户的 id 是 {user_id}。

工具使用规则：
1. 用户问到订单、物流、发货进度、最近买了什么时，必须调用 get_order_status，
   并把 user_id 参数设为 {user_id}，不要自己编造数字。
2. 用户问到退换货、保修、发票、配送时效，尤其是「拆封了还能不能退」这类售后政策时，
   必须先调用 search_policy 检索商城政策库，再依据检索到的条款回答；
   回答时点明依据的是第几条，检索不到就如实说没有相关规定，绝不能凭空编。
3. **写操作（取消订单）必须走两步**：用户明确要求取消时，先确认订单号
   （不确定就先调 get_order_status 查最近一笔），再调用 request_cancel_order
   生成待确认动作，然后把 actionId 和"请在页面点击确认"告诉用户。
   绝对不能声称订单已经取消——真正执行发生在用户确认之后。
4. 用户只是咨询"能不能取消""取消会怎样"时，不要生成动作，按政策回答即可。
5. 用户想买什么、要推荐商品时，不要自己编，说明"可以到商品页搜索"，不要调用工具。
6. 拿到工具结果后，用一到两句话自然语言转述，不要输出 JSON 原文。
"""


def build_agent(user_id: int) -> Any:
    return base.build_agent(
        tools=AGENT_TOOLS,
        system_prompt=SYSTEM_PROMPT.format(user_id=user_id),
    )


async def trim_thread_history(
    agent: Any, config: dict[str, Any], max_messages: int = MAX_HISTORY_MESSAGES
) -> int:
    return await base.trim_thread_history(agent, config, max_messages)


async def run_agent(user_id: int, message: str, session_id: str) -> tuple[str, list[str]]:
    """非流式：跑一轮对话，返回 (最终回答, 调用过的工具名)。"""
    return await base.run_once(build_agent(user_id), message, session_id)


async def stream_agent(
    user_id: int, message: str, session_id: str
) -> AsyncIterator[dict[str, Any]]:
    """流式：逐个 token 产出事件字典，供 SSE 层包装。"""
    async for event in base.stream_once(build_agent(user_id), message, session_id):
        yield event
