"""AI Agent 对话接口（SSE 流式 + 非流式兼容）。

- POST /api/ai/chat        → SSE 流式，前端可以边收边渲染（打字机效果）
- POST /api/ai/chat/sync   → 一次性 JSON，方便 curl 调试 / 单元测试 / 老调用方

两个接口共用同一份会话记忆：session_id 相同就能接着上一轮聊。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents.order_agent import AgentNotConfigured, run_agent, stream_agent
from app.core.config import settings
from app.core.exceptions import AppException
from app.models.agent import AgentChatData, AgentChatRequest, AgentChatResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["AI Agent"])


def _sse(payload: dict) -> str:
    """按 SSE 规范包装一条事件：data: {json}\\n\\n"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _ensure_configured() -> None:
    if not settings.llm_api_key:
        raise AppException("未配置 LLM_API_KEY，无法启动 Agent", code=503)


@router.post(
    "/api/ai/chat",
    summary="订单智能助理（SSE 流式）",
    description=(
        "流式返回，事件格式：\n\n"
        '- `{"type":"meta","session_id":"..."}` 会话信息\n'
        '- `{"type":"tool","name":"search_policy"}` 模型正在调工具\n'
        '- `{"type":"token","content":"..."}` 文本增量\n'
        '- `{"type":"done"}` 结束\n'
        '- `{"type":"error","message":"..."}` 异常'
    ),
)
async def chat_stream(req: AgentChatRequest) -> StreamingResponse:
    # 参数校验、密钥缺失这类错误在“开始推流之前”就返回普通 JSON，
    # 前端用 response.ok / status 就能判断，不用去解析流。
    _ensure_configured()

    session_id = req.session_id or uuid.uuid4().hex
    user_id, message = req.user_id, req.message

    async def event_stream() -> AsyncIterator[str]:
        # 先发一条 meta，前端可以立刻拿到 session_id 用于后续多轮
        yield _sse({"type": "meta", "session_id": session_id, "model": settings.llm_model})
        try:
            async for event in stream_agent(user_id, message, session_id):
                yield _sse(event)
            yield _sse({"type": "done", "session_id": session_id})
        except AgentNotConfigured as exc:  # pragma: no cover - 已在入口拦截
            yield _sse({"type": "error", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - 流已开始，只能通过事件告知前端
            logger.exception("Agent 流式执行失败 user_id=%s session=%s", user_id, session_id)
            yield _sse({"type": "error", "message": f"AI 助理暂时不可用：{exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 关键：告诉 Nginx 不要缓冲，否则前端会一次性收到全部内容
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/api/ai/chat/sync",
    response_model=AgentChatResponse,
    summary="订单智能助理（非流式）",
    description="和 /api/ai/chat 逻辑完全一致，只是等全部生成完一次性返回 JSON，便于调试。",
)
async def chat_sync(req: AgentChatRequest) -> AgentChatResponse:
    _ensure_configured()

    session_id = req.session_id or uuid.uuid4().hex
    try:
        reply, tools_used = await run_agent(req.user_id, req.message, session_id)
    except AgentNotConfigured as exc:
        raise AppException(str(exc), code=503) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent 执行失败 user_id=%s", req.user_id)
        raise AppException("AI 助理暂时不可用，请稍后重试", code=502, detail=str(exc)) from exc

    return AgentChatResponse(
        code=200,
        message="success",
        data=AgentChatData(
            reply=reply,
            session_id=session_id,
            model=settings.llm_model,
            tools_used=tools_used,
        ),
    )
