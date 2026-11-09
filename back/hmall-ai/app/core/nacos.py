"""Nacos 服务注册。

注册成功后，网关就能用 lb://hmall-ai 走服务发现，而不是在配置里写死 8000 端口。

实现要点：
- 用 nacos-sdk-python 2.x 的同步客户端（3.x 换成了 v2 命名空间，API 不兼容）；
- ephemeral=True + heartbeat_interval 让 SDK 自己发心跳，不用我们手写定时器；
- 注册/注销都放在线程池里执行，避免阻塞事件循环；
- 任何一步失败都只记日志，不影响服务本身可用（注册中心挂了也能用直连）。
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def _detect_local_ip() -> str:
    """探测本机对外 IP：连一个外网地址，看内核选了哪块网卡。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        sock.close()


class NacosRegistrar:
    def __init__(self) -> None:
        self._client: Any = None
        self.ip = ""
        self.port = 0

    async def startup(self) -> None:
        if not settings.nacos_enabled:
            logger.info("Nacos 注册：未开启（直连模式）")
            return

        try:
            from nacos import NacosClient
        except ImportError:
            logger.warning("未安装 nacos-sdk-python，跳过注册")
            return

        self.ip = settings.nacos_register_ip or _detect_local_ip()
        self.port = settings.nacos_register_port or settings.port

        try:
            self._client = await asyncio.to_thread(
                NacosClient,
                settings.nacos_server_addr,
                namespace=settings.nacos_namespace,
                username=settings.nacos_username or None,
                password=settings.nacos_password or None,
            )
            ok = await asyncio.to_thread(self._register)
        except Exception:  # noqa: BLE001 - 注册失败不影响服务可用
            logger.exception("Nacos 注册失败，服务继续以直连模式运行")
            self._client = None
            return

        if ok:
            logger.info(
                "已注册到 Nacos：service=%s group=%s addr=%s:%s",
                settings.nacos_service_name,
                settings.nacos_group,
                self.ip,
                self.port,
            )
        else:
            logger.warning("Nacos 返回注册失败，网关将无法通过 lb:// 找到本服务")

    def _register(self) -> bool:
        return self._client.add_naming_instance(
            settings.nacos_service_name,
            self.ip,
            self.port,
            group_name=settings.nacos_group,
            cluster_name="DEFAULT",
            weight=1.0,
            metadata={"framework": "fastapi", "env": settings.env},
            enable=True,
            healthy=True,
            ephemeral=True,
            # 交给 SDK 自动发心跳，避免临时实例被摘掉
            heartbeat_interval=5,
        )

    async def shutdown(self) -> None:
        if self._client is None:
            return
        try:
            await asyncio.to_thread(
                self._client.remove_naming_instance,
                settings.nacos_service_name,
                self.ip,
                self.port,
                group_name=settings.nacos_group,
            )
            logger.info("已从 Nacos 注销：%s", settings.nacos_service_name)
        except Exception:  # noqa: BLE001
            logger.warning("注销 Nacos 实例失败", exc_info=True)
        finally:
            self._client = None


nacos_registrar = NacosRegistrar()
