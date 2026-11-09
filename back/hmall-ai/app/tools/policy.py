"""政策知识库检索工具。

配合 ingest.py 使用：ingest.py 把 policy.txt 切块灌进 Milvus，
这个工具在对话时按问题去检索相关条款，交给模型总结。
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from app.core.config import settings
from app.services.embeddings import EmbeddingError
from app.services.policy import policy_store

logger = logging.getLogger(__name__)


@tool
async def search_policy(query: str) -> str:
    """检索黑马商城的售后政策知识库（退换货、保修、发票、配送等规则）。

    什么时候用：用户问「能不能退」「拆封了还能退吗」「保修多久」「发票怎么开」
    「多久发货」这类售后政策问题时调用。

    参数 query：把用户的问题改写成一句检索语句，保留关键约束
    （例如「拆封的手机能退吗」），不要加无关的客套话。
    """
    if not settings.siliconflow_api_key:
        return "知识库检索未配置（缺少 SILICONFLOW_API_KEY），暂时无法回答售后政策问题。"

    try:
        rows = await policy_store.search(query)
    except EmbeddingError as exc:
        logger.warning("政策检索 embedding 失败: %s", exc)
        return f"知识库检索失败：{exc}"
    except Exception as exc:  # noqa: BLE001 - Milvus 不可用等
        logger.warning("政策检索失败: %s", exc)
        return f"知识库暂时不可用：{exc}"

    if not rows:
        return "知识库中没有检索到相关条款。"

    lines = ["检索到的政策条款（按相关度排序）："]
    for idx, row in enumerate(rows, 1):
        text = (row.get("text") or "").replace("\n", " ").strip()
        lines.append(f"[{idx}] {text}")
    return "\n".join(lines)
