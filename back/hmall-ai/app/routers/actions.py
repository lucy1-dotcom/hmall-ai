"""待确认动作（写操作）的确认 / 取消接口。

前端流程：
1. 用户在对话里说「帮我把订单取消」，Agent 调用 `request_cancel_order` 工具，
   返回 `{actionId, summary}`，并在正文里告诉用户「请点确认」；
2. 前端拿 actionId 调 `POST /ai/actions/{actionId}/confirm`；
3. 这里校验归属、状态机、是否过期，再真正调 Java 接口；
4. 返回执行结果。

PUT 语义上是幂等的，所以重复确认同一个动作会返回第一次的结果，不会重复执行。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.actions import ActionExecutionError, PendingAction, action_store, execute_action

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/actions", tags=["AI 写操作"])


class ActionRequest(BaseModel):
    user_id: int = Field(..., description="当前登录用户 id，用于校验动作归属")


class ActionResponse(BaseModel):
    actionId: str
    type: str
    summary: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


def _load(action_id: str) -> PendingAction:
    action = action_store.get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="动作不存在或已被清理")
    return action


def _to_response(action: PendingAction, message: str | None = None) -> ActionResponse:
    data = action.to_dict()
    return ActionResponse(
        actionId=data["actionId"],
        type=data["type"],
        summary=data["summary"],
        status=data["status"],
        result=data["result"],
        message=message,
    )


@router.get("/{action_id}", response_model=ActionResponse, summary="查询动作状态")
def get_action(action_id: str) -> ActionResponse:
    return _to_response(_load(action_id))


@router.post("/{action_id}/confirm", response_model=ActionResponse, summary="确认并执行动作")
async def confirm_action(action_id: str, req: ActionRequest) -> ActionResponse:
    action = _load(action_id)

    if action.user_id != req.user_id:
        # 不暴露动作详情，避免越权探测
        raise HTTPException(status_code=403, detail="无权操作该动作")

    if action.status == "done":
        # 幂等：重复点确认返回第一次的结果
        return _to_response(action, message="该操作已执行，返回首次执行结果")

    if action.status in {"cancelled", "expired", "failed"}:
        raise HTTPException(status_code=409, detail=f"动作当前状态为 {action.status}，无法执行")

    if action.status == "executing":
        raise HTTPException(status_code=409, detail="动作正在执行中，请稍候")

    # 先占位再执行：并发点两次时只有一个能把 pending 改成 executing
    action_store.mark(action.id, "executing")
    try:
        result = await execute_action(action)
    except ActionExecutionError as exc:
        action_store.mark(action.id, "failed", {"error": str(exc)})
        logger.warning("动作执行失败 %s: %s", action.id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 未预期异常也要落状态，避免卡在 executing
        action_store.mark(action.id, "failed", {"error": str(exc)})
        logger.exception("动作执行异常 %s", action.id)
        raise HTTPException(status_code=500, detail="动作执行失败，请稍后重试") from exc

    action_store.mark(action.id, "done", result)
    logger.info("动作执行成功 %s type=%s user=%s", action.id, action.action_type, action.user_id)
    return _to_response(action_store.get(action.id) or action, message="执行成功")


@router.post("/{action_id}/cancel", response_model=ActionResponse, summary="取消动作")
def cancel_action(action_id: str, req: ActionRequest) -> ActionResponse:
    action = _load(action_id)
    if action.user_id != req.user_id:
        raise HTTPException(status_code=403, detail="无权操作该动作")
    if action.status == "done":
        raise HTTPException(status_code=409, detail="动作已执行，无法取消")
    if action.status == "cancelled":
        return _to_response(action, message="该动作已取消")

    action_store.mark(action.id, "cancelled")
    return _to_response(action_store.get(action.id) or action, message="已取消，订单未做任何修改")
