"""LLM 能力封装（全项目统一配置）。

两个原则：
1. 只读 settings.llm_*，不再区分 OpenAI / DeepSeek —— 换模型改环境变量即可；
2. 重依赖（langchain_openai）延迟导入，没配 key 时返回演示话术并标记 degraded，
   保证服务能起来、接口能联调。
"""

from __future__ import annotations

import logging
from typing import Sequence

from app.core.config import settings
from app.models.chat import ChatMessage

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是黑马商城（hmall）的智能客服，语气友好、回答简洁。
规则：
1. 只根据「参考资料」回答，资料里没有的信息不要编造，直接说明暂时查不到；
2. 涉及价格时以参考资料为准，不要自己换算；
3. 回答控制在 3 句话以内，必要时用序号列出要点。"""

DEMO_ANSWER = (
    "【演示模式】当前没有配置大模型密钥（LLM_API_KEY），"
    "所以这台 AI 服务只验证了链路是通的。配置密钥后即可返回真实回答。"
)


class LLMService:
    """对 LangChain ChatModel 的薄封装。"""

    def __init__(self) -> None:
        self._model = None

    @property
    def configured(self) -> bool:
        """是否配置了可用的模型密钥。"""
        return bool(settings.llm_api_key)

    def _get_model(self):
        if self._model is None:
            # 延迟导入：只有真正要调模型时才依赖 langchain
            from langchain_openai import ChatOpenAI

            self._model = ChatOpenAI(
                model=settings.llm_model,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url or None,
                temperature=settings.llm_temperature,
                timeout=settings.llm_timeout,
                max_retries=1,
            )
        return self._model

    def chat(
        self,
        question: str,
        *,
        context: str = "",
        history: Sequence[ChatMessage] | None = None,
    ) -> tuple[str, bool]:
        """返回 (回答, 是否降级)。"""
        if not self.configured:
            logger.info("未配置 LLM_API_KEY，返回演示回答")
            return DEMO_ANSWER, True

        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        messages: list = [SystemMessage(content=SYSTEM_PROMPT)]
        for msg in (history or [])[-10:]:  # 只保留最近 10 条，控制 token
            if msg.role == "user":
                messages.append(HumanMessage(content=msg.content))
            elif msg.role == "assistant":
                messages.append(AIMessage(content=msg.content))
            else:
                messages.append(SystemMessage(content=msg.content))

        if context:
            prompt = f"参考资料：\n{context}\n\n用户问题：{question}"
        else:
            prompt = question
        messages.append(HumanMessage(content=prompt))

        answer = self._get_model().invoke(messages).content
        return str(answer).strip(), False


llm_service = LLMService()
