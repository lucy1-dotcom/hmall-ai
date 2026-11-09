"""订单助理 Agent（带会话记忆 + 流式输出）。

组成：
1. ChatOpenAI —— base_url 指向 DeepSeek（兼容 OpenAI 协议）；
2. 工具集 —— 订单查询 get_order_status、政策检索 search_policy；
3. create_agent —— 装配模型与工具；
4. InMemorySaver（LangGraph 的 MemorySaver）—— 按 thread_id 保存会话状态，
   thread_id 用前端传来的 session_id，这样就实现了多轮记忆；
5. 裁剪 —— 历史超过 10 条时只保留最近 10 条（约 5 轮）。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage, RemoveMessage, ToolMessage

from app.core.config import settings
from app.core.memory import memory_store
from app.tools.order import get_order_status
from app.tools.policy import search_policy

logger = logging.getLogger(__name__)


class AgentNotConfigured(RuntimeError):
    """没有配置大模型密钥。"""


# 工具集中在一处，便于测试断言和后续扩展
AGENT_TOOLS = [get_order_status, search_policy]

# ---------------------------------------------------------------------------
# 会话记忆
# ---------------------------------------------------------------------------
# 由 app.core.memory 统一管理：默认 SQLite 落盘，重启不丢；测试可切内存模式。
# 超过这么多条消息就裁剪（一轮问答约 2 条，5 轮 ≈ 10 条）
MAX_HISTORY_MESSAGES = 10


def thread_config(session_id: str) -> dict[str, Any]:
    """LangGraph 用 thread_id 区分会话，这里直接复用前端的 session_id。"""
    return {"configurable": {"thread_id": session_id}}


SYSTEM_PROMPT = """你是黑马商城（hmall）的智能客服，说话简洁、礼貌，用中文回答。

当前登录用户的 id 是 {user_id}。

工具使用规则：
1. 用户问到订单、物流、发货进度、最近买了什么时，必须调用 get_order_status，
   并把 user_id 参数设为 {user_id}，不要自己编造数字。
2. 用户问到退换货、保修、发票、配送时效，尤其是「拆封了还能不能退」这类售后政策时，
   必须先调用 search_policy 检索商城政策库，再依据检索到的条款回答；
   回答时点明依据的是第几条，检索不到就如实说没有相关规定，绝不能凭空编。
3. 其它问题（商品咨询、闲聊）直接回答，不要调用工具。
4. 拿到工具结果后，用一到两句话自然语言转述，不要输出 JSON 原文。
5. 记住上文已经确认过的事实（例如用户说过自己的订单号），不要重复追问。
"""


def _build_llm() -> Any:
    """构造 ChatModel（默认 DeepSeek，配置来自 settings.llm_*）。"""
    if not settings.llm_api_key:
        raise AgentNotConfigured("未配置 LLM_API_KEY，无法启动 Agent")

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url or None,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout,
        max_retries=1,
    )


def build_agent(user_id: int) -> Any:
    """构造 Agent。

    每个请求新建图对象是廉价的（编译一次几十毫秒），
    真正的会话状态存在共享的 checkpointer 里（SQLite），按 thread_id 区分。
    system_prompt 里带了 user_id，所以不能全局只建一个。
    """
    from langchain.agents import create_agent

    return create_agent(
        model=_build_llm(),
        tools=AGENT_TOOLS,
        system_prompt=SYSTEM_PROMPT.format(user_id=user_id),
        checkpointer=memory_store.saver,
    )


async def trim_thread_history(
    agent: Any,
    config: dict[str, Any],
    max_messages: int = MAX_HISTORY_MESSAGES,
) -> int:
    """历史过长时只保留最近 max_messages 条，返回删掉的条数。

    注意：不能从一条工具调用中间切（留着 tool_calls 却丢了 tool 结果，
    模型接口会直接报错），所以切点会向后对齐到最近的用户消息。
    """
    snapshot = await agent.aget_state(config)
    messages: list[Any] = list((snapshot.values or {}).get("messages", []))
    if len(messages) <= max_messages:
        return 0

    cut = len(messages) - max_messages
    while cut < len(messages) and not isinstance(messages[cut], HumanMessage):
        cut += 1
    if cut <= 0:
        return 0

    removed = messages[:cut]
    await agent.aupdate_state(
        config, {"messages": [RemoveMessage(id=m.id) for m in removed]}
    )
    logger.info("会话历史裁剪：删除 %d 条，保留 %d 条", len(removed), len(messages) - cut)
    return len(removed)


def _text_of(content: Any) -> str:
    """把消息内容统一成字符串（多模态时是 list）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return "" if content is None else str(content)


async def run_agent(
    user_id: int, message: str, session_id: str
) -> tuple[str, list[str]]:
    """非流式：跑一轮对话，返回 (最终回答, 调用过的工具名)。"""
    agent = build_agent(user_id)
    config = thread_config(session_id)
    await trim_thread_history(agent, config)

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": message}]},
        config={**config, "recursion_limit": 8},
    )

    messages: list[Any] = list(result.get("messages", []))
    tools_used = [
        str(call.get("name") if isinstance(call, dict) else getattr(call, "name", ""))
        for msg in messages
        for call in (getattr(msg, "tool_calls", None) or [])
    ]
    tools_used = [name for name in tools_used if name]
    return (_text_of(getattr(messages[-1], "content", "")) if messages else ""), tools_used


async def stream_agent(
    user_id: int,
    message: str,
    session_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """流式：逐个 token 产出事件字典，供 SSE 层包装。

    事件类型：
      {"type": "tool",  "name": "search_policy"}   模型决定调用工具
      {"type": "token", "content": "根据"}          模型吐出的一个片段
    """
    agent = build_agent(user_id)
    config = thread_config(session_id)
    await trim_thread_history(agent, config)

    # stream_mode="messages" 会把模型输出按 token 切片吐出来，
    # 这就是前端打字机效果的数据源。
    async for chunk, _metadata in agent.astream(
        {"messages": [{"role": "user", "content": message}]},
        config={**config, "recursion_limit": 8},
        stream_mode="messages",
    ):
        # 工具返回值是给模型看的中间结果，不应该出现在正文里
        if isinstance(chunk, ToolMessage):
            continue

        # 工具调用消息没有正文，只把工具名告诉前端（可以显示“正在查询…”）
        tool_calls = getattr(chunk, "tool_calls", None) or []
        for call in tool_calls:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                yield {"type": "tool", "name": str(name)}

        text = _text_of(getattr(chunk, "content", ""))
        if text:
            yield {"type": "token", "content": text}
