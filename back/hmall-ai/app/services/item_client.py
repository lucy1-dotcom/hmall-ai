"""调用 Java 微服务（经网关）。

AI 服务不直连 MySQL，也不直连 item-service，统一走网关 8080，
这样网关上的鉴权、路由、限流对 AI 服务同样生效。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class ItemClient:
    """商品相关接口的 HTTP 客户端。"""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.hmall_gateway_url).rstrip("/")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=settings.http_timeout) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    def search_items(self, key: str, size: int = 10) -> list[dict[str, Any]]:
        """关键词搜索，走网关 -> item-service 的 /search/list。"""
        data = self._get("/search/list", {"key": key, "pageNo": 1, "pageSize": size})
        return list(data.get("list") or []) if isinstance(data, dict) else []

    def get_item(self, item_id: str | int) -> dict[str, Any] | None:
        """按 id 查商品详情。"""
        try:
            data = self._get(f"/items/{item_id}")
            return data if isinstance(data, dict) and data.get("id") else None
        except httpx.HTTPError as exc:
            logger.warning("查询商品 %s 失败: %s", item_id, exc)
            return None


item_client = ItemClient()
