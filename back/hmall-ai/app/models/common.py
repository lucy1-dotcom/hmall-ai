"""通用数据模型。"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应包装：和 Java 侧 Result 结构对齐，前端好统一处理。"""

    code: int = Field(default=200, description="业务状态码，200 表示成功")
    message: str = Field(default="success", description="提示信息")
    data: T | None = Field(default=None, description="业务数据")


class ErrorResponse(BaseModel):
    code: int = Field(description="错误码，等同 HTTP 状态码")
    message: str = Field(description="错误信息")
    detail: Any | None = Field(default=None, description="补充信息（参数名、原因等）")


class HealthResponse(BaseModel):
    status: str = Field(default="UP", description="UP / DOWN")
    service: str
    version: str
    env: str
    time: str = Field(description="服务器当前时间 ISO8601")
    components: dict[str, Any] = Field(default_factory=dict, description="各依赖组件的状态")
