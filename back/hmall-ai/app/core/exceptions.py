"""统一异常与响应格式。

错误响应统一成 {"code": 4xx/5xx, "message": "...", "detail": ...}，
前端（axios）拿到的结构和 Java 侧的 BusinessException 基本一致，好处理。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppException(Exception):
    """业务异常，例如参数不合法、上游服务不可用。"""

    def __init__(
        self,
        message: str,
        *,
        code: int = status.HTTP_400_BAD_REQUEST,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail


def _error_response(code: int, message: str, detail: Any = None) -> JSONResponse:
    return JSONResponse(status_code=code, content={"code": code, "message": message, "detail": detail})


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def _app_exception(_: Request, exc: AppException) -> JSONResponse:
        return _error_response(exc.code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        # 直接写 422：Starlette 新版把 HTTP_422_UNPROCESSABLE_ENTITY 改名了，
        # 用字面量可以同时兼容新旧版本
        return _error_response(
            422,
            "参数校验失败",
            {"field": ".".join(str(x) for x in first.get("loc", [])), "reason": first.get("msg", "")},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常: %s %s", request.method, request.url.path)
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "服务内部错误", str(exc) if logger.isEnabledFor(logging.DEBUG) else None
        )
