"""健康检查与探活。

Spring Cloud / Nacos / K8s 都靠这个判断实例是否可用，所以它不能依赖
任何外部组件（大模型、Milvus）——只报告配置状态，不发起真实调用。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from app.core.config import settings
from app.models.common import HealthResponse
from app.services.llm import llm_service

router = APIRouter(tags=["健康检查"])


@router.get("/health", response_model=HealthResponse, summary="健康检查")
def health() -> HealthResponse:
    return HealthResponse(
        status="UP",
        service=settings.app_name,
        version=settings.app_version,
        env=settings.env,
        time=datetime.now().isoformat(timespec="seconds"),
        components={
            "llm": {"configured": llm_service.configured, "model": settings.llm_model},
            "milvus": {"uri": settings.milvus_uri, "collection": settings.milvus_collection},
            "gateway": {"url": settings.hmall_gateway_url},
        },
    )


@router.get("/ping", summary="轻量探活")
def ping() -> dict[str, str]:
    """只回一个 pong，给心跳/负载均衡用，不查任何依赖。"""
    return {"message": "pong"}
