"""会话记忆与裁剪的单元测试（不需要真实模型）。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.order_agent import MAX_HISTORY_MESSAGES, thread_config, trim_thread_history


class FakeAgent:
    """只实现 trim_thread_history 需要的两个方法。"""

    def __init__(self, messages: list) -> None:
        self.messages = list(messages)

    async def aget_state(self, _config):  # noqa: ANN001
        return SimpleNamespace(values={"messages": self.messages})

    async def aupdate_state(self, _config, values):  # noqa: ANN001
        removed = {m.id for m in values["messages"]}
        self.messages = [m for m in self.messages if m.id not in removed]


def _dialog(turns: int) -> list:
    """生成 turns 轮「用户 + AI」的对话。"""
    messages = []
    for i in range(turns):
        messages.append(HumanMessage(content=f"第{i}问", id=f"u{i}"))
        messages.append(AIMessage(content=f"第{i}答", id=f"a{i}"))
    return messages


def test_thread_id_is_session_id() -> None:
    assert thread_config("abc")["configurable"]["thread_id"] == "abc"


def test_no_trim_when_short() -> None:
    agent = FakeAgent(_dialog(3))
    removed = asyncio.run(trim_thread_history(agent, {}, max_messages=10))
    assert removed == 0
    assert len(agent.messages) == 6


def test_trim_keeps_last_ten_messages() -> None:
    """8 轮 = 16 条，裁到最近 10 条。"""
    agent = FakeAgent(_dialog(8))
    removed = asyncio.run(trim_thread_history(agent, {}, max_messages=MAX_HISTORY_MESSAGES))
    assert removed == 6
    assert len(agent.messages) == 10
    # 裁剪后第一条必须是用户消息，不能从半轮开始
    assert isinstance(agent.messages[0], HumanMessage)
    assert agent.messages[-1].content == "第7答"


def test_trim_never_orphans_tool_messages() -> None:
    """如果切点落在 tool 消息上，要向后对齐，避免 tool_calls 没有结果。"""
    messages = [
        HumanMessage(content="问1", id="u1"),
        AIMessage(content="", id="a1", tool_calls=[{"name": "search_policy", "args": {}, "id": "c1"}]),
        ToolMessage(content="条款", tool_call_id="c1", id="t1"),
        AIMessage(content="答1", id="a2"),
    ]
    # 再加 7 轮，总共 18 条，强制裁剪
    messages += _dialog(7)
    for i, m in enumerate(messages):
        if m.id is None:
            m.id = f"x{i}"

    agent = FakeAgent(messages)
    asyncio.run(trim_thread_history(agent, {}, max_messages=10))

    assert len(agent.messages) <= 10
    first = agent.messages[0]
    assert isinstance(first, HumanMessage), "裁剪后必须从用户消息开始"
    # 保留下来的 tool 消息，其 tool_call_id 必须能在保留区里找到对应的 AIMessage
    kept_call_ids = {
        call["id"]
        for m in agent.messages
        if isinstance(m, AIMessage)
        for call in (m.tool_calls or [])
    }
    for m in agent.messages:
        if isinstance(m, ToolMessage):
            assert m.tool_call_id in kept_call_ids
