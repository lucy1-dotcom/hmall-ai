"""会话记忆的存储后端。

默认用 SQLite（LangGraph 的 AsyncSqliteSaver）：
- 落盘，服务重启后会话还在；
- 单文件，不用额外起服务，适合课程/毕设场景。

要换成 Postgres 或集群方案，只改这里，业务代码（build_agent / trim_thread_history）不用动。
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# LangGraph 新版本叫 InMemorySaver，老版本叫 MemorySaver，这里做一次兼容
try:  # pragma: no cover - 取决于安装的版本
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError:  # pragma: no cover
    from langgraph.checkpoint.memory import MemorySaver as InMemorySaver


class MemoryStore:
    """持有 checkpointer 实例，生命周期跟着 FastAPI 走。"""

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._saver = None
        # 兜底：SQLite 不可用（没装依赖/目录没权限）时退回内存，服务不至于起不来
        self._fallback = InMemorySaver()

    async def startup(self) -> None:
        if settings.memory_backend.lower() != "sqlite":
            logger.info("会话记忆：内存模式（重启即清空）")
            self._saver = self._fallback
            return

        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError:
            logger.warning("未安装 langgraph-checkpoint-sqlite，会话记忆回退到内存模式")
            self._saver = self._fallback
            return

        db_path = Path(settings.memory_db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._stack = AsyncExitStack()
        self._saver = await self._stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(db_path))
        )
        # 建表（幂等），第一次启动时执行
        await self._saver.setup()
        logger.info("会话记忆：SQLite（%s）", db_path.resolve())

    async def shutdown(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        self._saver = None

    @property
    def saver(self):
        """给 create_agent 用的 checkpointer。"""
        return self._saver or self._fallback


memory_store = MemoryStore()
