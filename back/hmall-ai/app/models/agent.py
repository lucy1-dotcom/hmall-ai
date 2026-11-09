"""AI Agent 的请求 / 响应模型。

响应统一包一层 {code, message, data}，和 Java 侧 Result 结构一致，
前端 axios 拦截器不用为 AI 接口单独写分支。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentChatRequest(BaseModel):
    """POST /api/ai/chat 的请求体。"""

    user_id: int = Field(gt=0, description="当前登录用户 id", examples=[1])
    message: str = Field(min_length=1, max_length=2000, description="用户的话", examples=["我的订单到哪了？"])
    session_id: str | None = Field(default=None, description="会话 id，不传则自动生成")


class AgentChatData(BaseModel):
    """真正返回给前端的业务数据。"""

    reply: str = Field(description="Agent 最终回答的文本")
    session_id: str = Field(description="会话 id")
    model: str = Field(description="使用的模型")
    tools_used: list[str] = Field(default_factory=list, description="本次调用过的工具名，便于排查")


class AgentChatResponse(BaseModel):
    """统一响应格式（和 app.models.common.ApiResponse 同构，这里显式写一份方便 Swagger 展示）。"""

    code: int = Field(default=200, description="业务状态码")
    message: str = Field(default="success", description="提示信息")
    data: AgentChatData | None = Field(default=None, description="业务数据")
