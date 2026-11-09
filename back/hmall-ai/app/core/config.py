"""应用配置。

所有可变项都走环境变量 / .env，代码里不写死密钥和地址，
这样本地、Docker、服务器可以用同一份镜像，只换配置。
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 默认值抽成常量，供「旧配置迁移」逻辑判断用户是否真的改过
_DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1"
_DEFAULT_LLM_MODEL = "deepseek-chat"


class Settings(BaseSettings):
    """服务配置项，字段名即环境变量名（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # 默认 pydantic-settings 会先把 List 字段当 JSON 解析，
        # 而 CORS_ORIGINS 我们用的是逗号分隔，所以关掉自动解码，
        # 交给下面的 field_validator 自己处理（两种写法都支持）。
        enable_decoding=False,
    )

    # ------------------------------------------------------------------ 基础
    app_name: str = "hmall-ai"
    app_version: str = "1.0.0"
    env: str = "dev"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    # 所有接口统一挂在 /ai 下：/ai/health、/ai/chat ...
    api_prefix: str = "/ai"
    log_level: str = "INFO"
    log_dir: str = "logs"

    # ------------------------------------------------------------------ CORS
    # 前端是 Nginx 上的静态页，端口 18080（商城）/18081（后台）/18082（数据后台）
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:18080",
            "http://127.0.0.1:18080",
            "http://localhost:18081",
            "http://127.0.0.1:18081",
            "http://localhost:18082",
            "http://127.0.0.1:18082",
        ]
    )
    # 允许携带 cookie / Authorization 头。注意：CORS 规范里 allow_credentials=True
    # 时不能用 allow_origins=["*"]，application.py 里已经做了兼容处理。
    cors_allow_credentials: bool = True

    # ------------------------------------------------------------------- LLM
    # 全项目只认这一套：所有大模型调用（Agent、RAG 问答）都读 llm_*。
    # 默认 DeepSeek（兼容 OpenAI 协议）；换 OpenAI / 通义 / Kimi 只要改
    # LLM_BASE_URL + LLM_MODEL，代码不用动。
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.0
    llm_timeout: int = 60

    # 旧变量名（老 .env 里可能还是这些），启动时自动收敛到 llm_*，不必手改文件
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""

    # ------------------------------------------------------------ Embedding
    # 统一走硅基流动（OpenAI 兼容的 /v1/embeddings），bge-m3 中文效果好、1024 维。
    # 商品语义检索与政策库共用这一套，不再需要 OpenAI 的 embedding。
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    # 旧变量名（兼容）
    policy_embedding_model: str = ""
    policy_embedding_dim: int = 0

    # ---------------------------------------------------------------- Milvus
    milvus_uri: str = "http://localhost:19530"
    milvus_token: str = ""
    milvus_collection: str = "hmall_items"
    policy_collection: str = "hmall_policy"
    policy_top_k: int = 3
    policy_file: str = "policy.txt"

    # ------------------------------------------------------------- 业务微服务
    # 通过网关访问 item-service / search 等 Java 服务
    hmall_gateway_url: str = "http://localhost:8080"
    http_timeout: float = 5.0
    # 订单助理用的 Java 接口路径（拼在 hmall_gateway_url 后面）
    order_latest_path: str = "/api/order/latest"

    # ------------------------------------------------------------- 会话记忆
    # sqlite：落盘，重启服务会话还在（默认）
    # memory：进程内，重启即清空（跑测试用）
    memory_backend: str = "sqlite"
    memory_db_path: str = "data/memory.db"

    # ------------------------------------------------------- Nacos 服务注册
    # 打开后网关就能用 lb://hmall-ai 走服务发现，而不是写死地址
    nacos_enabled: bool = False
    nacos_server_addr: str = "192.168.150.131:8848"
    nacos_namespace: str = "public"
    nacos_username: str = ""
    nacos_password: str = ""
    nacos_service_name: str = "hmall-ai"
    nacos_group: str = "DEFAULT_GROUP"
    # 留空则自动探测本机出口 IP；容器/K8s 里建议显式指定
    nacos_register_ip: str = ""
    # 0 表示用服务实际监听端口
    nacos_register_port: int = 0

    # ------------------------------------------------------------------ 校验
    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value):
        """支持 CORS_ORIGINS=a,b,c 这种逗号分隔写法，也支持 JSON 数组。"""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("["):
                # 关了自动解码，JSON 数组这里自己解
                import json

                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _unify_legacy_settings(self) -> "Settings":
        """把旧变量名收敛到统一配置，老 .env / 老环境变量不用改就能继续用。"""
        # 1) 大模型：DEEPSEEK_API_KEY / OPENAI_API_KEY -> LLM_API_KEY
        if not self.llm_api_key:
            if self.deepseek_api_key:
                self.llm_api_key = self.deepseek_api_key
            elif self.openai_api_key:
                self.llm_api_key = self.openai_api_key
                # 只配了 OPENAI_API_KEY 时，把默认的 DeepSeek 地址换成 OpenAI 的
                if self.llm_base_url == _DEFAULT_LLM_BASE_URL:
                    self.llm_base_url = self.openai_base_url or "https://api.openai.com/v1"
                    if self.llm_model == _DEFAULT_LLM_MODEL:
                        self.llm_model = "gpt-4o-mini"

        # 2) Embedding：POLICY_EMBEDDING_* -> EMBEDDING_*
        if self.policy_embedding_model:
            self.embedding_model = self.policy_embedding_model
        if self.policy_embedding_dim:
            self.embedding_dim = self.policy_embedding_dim

        return self


@lru_cache
def get_settings() -> Settings:
    """单例配置，避免每次请求都读一遍 .env。"""
    return Settings()


settings = get_settings()
