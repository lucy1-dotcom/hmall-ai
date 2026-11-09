"""Milvus 向量库的数据访问封装。

设计要点：
- pymilvus 是重依赖，**延迟导入**：没装也不会影响服务启动和其它接口；
- 连接失败时抛 VectorStoreUnavailable，让上层做降级（关键词搜索）；
- 只暴露 CRUD 四个动作，业务逻辑放在 services/vector_store.py。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Iterable, Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)


class VectorStoreUnavailable(RuntimeError):
    """向量库不可用（未安装、连不上、集合不存在）。"""


def _new_id() -> str:
    return uuid.uuid4().hex


class MilvusRepository:
    """Milvus 集合的最小操作封装。"""

    def __init__(self, collection: str | None = None) -> None:
        self.collection = collection or settings.milvus_collection
        self._client: Any | None = None

    # ------------------------------------------------------------------ 连接
    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from pymilvus import MilvusClient  # 延迟导入，见模块说明
        except ImportError as exc:  # pragma: no cover - 依赖没装时的兜底
            raise VectorStoreUnavailable("未安装 pymilvus，无法使用向量检索") from exc

        try:
            self._client = MilvusClient(uri=settings.milvus_uri, token=settings.milvus_token or None)
            logger.info("已连接 Milvus: %s", settings.milvus_uri)
        except Exception as exc:  # noqa: BLE001 - 任何连接异常都统一降级
            raise VectorStoreUnavailable(f"连接 Milvus 失败: {exc}") from exc
        return self._client

    # ------------------------------------------------------------------ 建表
    def ensure_collection(self, dim: int | None = None) -> None:
        """集合不存在时按维度创建（COSINE 距离，主键为字符串）。"""
        dim = dim or settings.embedding_dim
        client = self.client
        if client.has_collection(self.collection):
            return
        client.create_collection(
            collection_name=self.collection,
            dimension=dim,
            primary_field_name="id",
            vector_field_name="vector",
            id_type="string",
            # Milvus 3.x 起，VARCHAR 主键必须显式给 max_length，否则建表报
            # "type param(max_length) should be specified"。
            # 这里用 md5(32 位) 或 uuid(32 位) 作主键，64 足够。
            max_length=64,
            auto_id=False,
            metric_type="COSINE",
            consistency_level="Bounded",
        )
        logger.info("已创建集合 %s（dim=%s）", self.collection, dim)

    # ------------------------------------------------------------------ 写入
    def upsert(self, records: Iterable[dict[str, Any]]) -> int:
        """写入/更新向量。每条记录需含 vector、text、item_id 等字段。"""
        rows = list(records)
        if not rows:
            return 0
        for row in rows:
            row.setdefault("id", _new_id())
        self.client.upsert(collection_name=self.collection, data=rows)
        return len(rows)

    # ------------------------------------------------------------------ 查询
    def search(
        self,
        vector: Sequence[float],
        top_k: int = 10,
        *,
        filter_expr: str | None = None,
        output_fields: Sequence[str] = ("text", "item_id", "name"),
    ) -> list[dict[str, Any]]:
        """按向量检索，返回 [{'id':..., 'score':..., 'text':...}, ...]。"""
        hits = self.client.search(
            collection_name=self.collection,
            data=[list(vector)],
            limit=top_k,
            filter=filter_expr or "",
            output_fields=list(output_fields),
        )
        if not hits:
            return []
        results: list[dict[str, Any]] = []
        for hit in hits[0]:
            payload = dict(hit.get("entity") or {})
            payload["id"] = str(hit.get("id"))
            payload["score"] = float(hit.get("distance", 0.0))
            results.append(payload)
        return results

    # ------------------------------------------------------------------ 删除
    def delete(self, ids: Iterable[str]) -> int:
        id_list = [str(i) for i in ids]
        if not id_list:
            return 0
        self.client.delete(collection_name=self.collection, ids=id_list)
        return len(id_list)

    def drop(self) -> None:
        """删除整个集合，调试用。"""
        if self.client.has_collection(self.collection):
            self.client.drop_collection(self.collection)
