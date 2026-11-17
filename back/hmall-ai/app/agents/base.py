"""Agent 运行时：构造 / 记忆裁剪 / 运行 / 流式。

售后 Agent 和导购 Agent 的差别只有「工具集 + 系统提示词」，
其余（会话记忆、历史裁剪、流式事件解析）完全一样，抽到这里避免复制粘贴。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Sequence

from langchain_core.messages import HumanMessage, RemoveMessage, ToolMessage

from app.core.config import settings
from app.core.memory import memory_store

logger = logging.getLogger(__name__)


class AgentNotConfigured(RuntimeError):
    """没有配置大模型密钥。"""


# 超过这么多条消息就裁剪（一轮问答约 2 条，5 轮 ≈ 10 条）
MAX_HISTORY_MESSAGES = 10


def thread_config(session_id: str) -> dict[str, Any]:
    """LangGraph 用 thread_id 区分会话，这里直接复用前端的 session_id。"""
    return {"configurable": {"thread_id": session_id}}


def build_llm() -> Any:
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


def build_agent(*, tools: Sequence[Any], system_prompt: str) -> Any:
    """按「工具集 + 系统提示」构造 Agent 图。

    每个请求新建图对象是廉价的（编译一次几十毫秒），
    真正的会话状态存在共享的 checkpointer 里（SQLite），按 thread_id 区分。
    """
    from langchain.agents import create_agent

    return create_agent(
        model=build_llm(),
        tools=list(tools),
        system_prompt=system_prompt,
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


def text_of(content: Any) -> str:
    """把消息内容统一成字符串（多模态时是 list）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return "" if content is None else str(content)


async def run_once(agent: Any, message: str, session_id: str) -> tuple[str, list[str]]:
    """非流式：跑一轮对话，返回 (最终回答, 调用过的工具名)。"""
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
    return (text_of(getattr(messages[-1], "content", "")) if messages else ""), tools_used


async def stream_once(
    agent: Any, message: str, session_id: str
) -> AsyncIterator[dict[str, Any]]:
    """流式：逐个 token 产出事件字典，供 SSE 层包装。

    事件类型：
      {"type": "tool",  "name": "search_policy"}   模型决定调用工具
      {"type": "token", "content": "根据"}          模型吐出的一个片段
    """
    config = thread_config(session_id)
    await trim_thread_history(agent, config)

    # stream_mode="messages" 会把模型输出按 token 切片吐出来，这就是打字机效果的数据源
    async for chunk, _metadata in agent.astream(
        {"messages": [{"role": "user", "content": message}]},
        config={**config, "recursion_limit": 8},
        stream_mode="messages",
    ):
        # 工具返回值是给模型看的中间结果，不应该出现在正文里
        if isinstance(chunk, ToolMessage):
            continue

        # 工具调用消息没有正文，只把工具名告诉前端（可以显示"正在查询…"）
        for call in (getattr(chunk, "tool_calls", None) or []):
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                yield {"type": "tool", "name": str(name)}

        text = text_of(getattr(chunk, "content", ""))
        if text:
            yield {"type": "token", "content": text}
