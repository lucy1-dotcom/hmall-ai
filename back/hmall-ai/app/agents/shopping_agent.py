"""导购 Agent：基于 Milvus 商品语义检索做推荐。

和售后 Agent 分开的理由：
- 工具完全不同（这边只有一个 search_products），混在一起模型容易乱调工具
  （比如问"能退吗"时去搜商品）；
- 系统提示可以写得更聚焦（导购要的是"推荐得像人"，售后要的是"严格依据条款"）。
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from app.agents import base
from app.tools.catalog import search_products

AGENT_TOOLS = [search_products]

SYSTEM_PROMPT = """你是黑马商城的导购助手，帮用户挑到合适的商品，说话简洁、自然，用中文。

工具使用规则：
1. 用户表达购买或推荐需求时（"想买个…""推荐…""有没有…""哪个适合…"），
   先调用 search_products。query 要改写成**商品描述**，不要带"我想买"这类客套话，
   例如用户说"想给女朋友买个生日礼物，预算五百"，query 写成"适合送女朋友的女式钱包 手拿包"。
2. 拿到结果后推荐 2-3 件，说明推荐理由（适合场景、价格档位），不要罗列超过 3 件。
3. **价格单位是分**，展示时要换算成元（例如 61800 → 618 元）。
4. 检索不到相关商品就如实说"暂时没有找到合适的"，并建议换个说法，绝不能编造商品。
5. 用户问退换货、保修、发票这类政策问题，不要调用工具，告诉他可以直接问售后 —— 会有专门的助手回答。
6. 不要把工具的 JSON 原样贴出来，用自然语言说。
"""


def build_agent(user_id: int) -> Any:
    return base.build_agent(
        tools=AGENT_TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )


async def run_agent(user_id: int, message: str, session_id: str) -> tuple[str, list[str]]:
    return await base.run_once(build_agent(user_id), message, session_id)


async def stream_agent(
    user_id: int, message: str, session_id: str
) -> AsyncIterator[dict[str, Any]]:
    async for event in base.stream_once(build_agent(user_id), message, session_id):
        yield event
