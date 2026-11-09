"""日志初始化：控制台 + 滚动文件，风格跟 Java 服务保持一致。"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from app.core.config import settings

_LOG_FORMAT = "%(asctime)s %(levelname)-5s %(name)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_configured = False


def setup_logging() -> None:
    """初始化根日志器，重复调用是安全的。"""
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        os.makedirs(settings.log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(settings.log_dir, f"{settings.app_name}.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:  # 日志目录没权限时不影响服务启动
        logging.getLogger(__name__).warning("文件日志初始化失败，仅输出到控制台: %s", exc)

    # 第三方库噪音降一档
    for noisy in ("httpx", "httpcore", "urllib3", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
