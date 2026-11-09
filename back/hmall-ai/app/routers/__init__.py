"""路由汇总：所有接口统一挂到 settings.api_prefix（默认 /ai）下。"""

from fastapi import APIRouter

from app.routers import chat, health, knowledge, search

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(search.router)
api_router.include_router(knowledge.router)

__all__ = ["api_router"]
