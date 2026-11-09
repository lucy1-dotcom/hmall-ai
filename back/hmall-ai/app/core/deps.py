"""FastAPI 依赖注入。

现在只有配置和几个单例服务；以后接数据库、鉴权可以往这里加。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from app.core.config import Settings, get_settings


def get_config() -> Settings:
    return get_settings()


ConfigDep = Annotated[Settings, Depends(get_config)]


def get_user_id(authorization: Annotated[str | None, Header()] = None) -> int | None:
    """和 Java 侧对齐：网关注入的 Authorization 头（JWT）里带 userId。

    现在只是占位实现，真正的解析逻辑等接入网关鉴权时再补，
    这样 AI 服务就能按用户做个性化推荐、限流等。
    """
    if not authorization:
        return None
    return None
