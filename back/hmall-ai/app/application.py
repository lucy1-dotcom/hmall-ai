"""FastAPI 应用工厂：装配 CORS、异常处理、路由和生命周期事件。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.memory import memory_store
from app.core.nacos import nacos_registrar
from app.routers import api_router
from app.routers import agent as agent_routes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动 / 关闭时的钩子，替代过时的 @app.on_event。"""
    logger.info(
        "%s v%s 启动 | env=%s | %s:%s | 文档 http://127.0.0.1:%s/docs",
        settings.app_name,
        settings.app_version,
        settings.env,
        settings.host,
        settings.port,
        settings.port,
    )
    # 会话记忆（SQLite）与 Nacos 注册都在这里初始化，失败会降级而不是让服务起不来
    await memory_store.startup()
    await nacos_registrar.startup()

    yield

    await nacos_registrar.shutdown()
    await memory_store.shutdown()
    logger.info("%s 已关闭", settings.app_name)


def register_cors(app: FastAPI) -> None:
    """跨域配置。

    前端（Nginx 静态页）跑在 18080/18081/18082，AI 服务在 8000，
    端口不同就是跨域，必须显式放行，否则浏览器直接拦掉响应。
    """
    origins = settings.cors_origins
    allow_all = "*" in origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else origins,
        # 浏览器规范：allow_origins=["*"] 时不能再允许携带凭证，
        # 否则预检响应会被判定非法，这里自动降级为 False。
        allow_credentials=False if allow_all else settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=600,
    )
    logger.info("CORS 已启用，允许来源: %s", "*" if allow_all else origins)


def create_app() -> FastAPI:
    """创建并返回 FastAPI 实例。"""
    setup_logging()

    app = FastAPI(
        title="hmall-ai 智能服务",
        version=settings.app_version,
        description=(
            "黑马商城 AI 微服务：\n\n"
            "- 智能客服（RAG：向量检索 + 大模型）\n"
            "- 自然语言商品搜索\n"
            "- 知识库向量写入\n\n"
            "接口文档见 /docs，健康检查见 /ai/health。"
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    register_cors(app)
    register_exception_handlers(app)

    # 常规接口统一挂 /ai 前缀（/ai/health、/ai/chat ...）
    app.include_router(api_router, prefix=settings.api_prefix)
    # Agent 接口按需求就是 /api/ai/chat，自带完整路径，不能再套前缀
    app.include_router(agent_routes.router)

    @app.get("/", include_in_schema=False)
    def index() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "api_prefix": settings.api_prefix,
            "health": f"{settings.api_prefix}/health",
        }

    return app
