"""会话记忆后端（SQLite）的测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.memory import MemoryStore


async def _run_lifecycle(store: MemoryStore) -> None:
    await store.startup()
    try:
        assert store.saver is not None
    finally:
        await store.shutdown()


def test_sqlite_backend_creates_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """sqlite 模式下应该真的落一个库文件，并且表结构建好。"""
    pytest.importorskip("langgraph.checkpoint.sqlite")

    db = tmp_path / "memory.db"
    monkeypatch.setattr(settings, "memory_backend", "sqlite")
    monkeypatch.setattr(settings, "memory_db_path", str(db))

    asyncio.run(_run_lifecycle(MemoryStore()))

    assert db.exists(), "SQLite 文件没有创建"
    # 表建好了才会有内容，至少能打开并查到 checkpoint 表
    import sqlite3

    with sqlite3.connect(db) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert any("checkpoint" in name for name in tables), f"没有 checkpoint 表：{tables}"


def test_memory_backend_needs_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """memory 模式不应产生任何文件（测试默认用这个）。"""
    monkeypatch.setattr(settings, "memory_backend", "memory")
    monkeypatch.setattr(settings, "memory_db_path", str(tmp_path / "should_not_exist.db"))

    asyncio.run(_run_lifecycle(MemoryStore()))

    assert not (tmp_path / "should_not_exist.db").exists()


def test_unknown_backend_falls_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "memory_backend", "redis-not-installed")
    store = MemoryStore()
    asyncio.run(_run_lifecycle(store))
