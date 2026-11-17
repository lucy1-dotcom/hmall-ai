"""意图识别：把用户问题分流到不同的 Agent。

为什么用规则而不是让大模型分类：
- 多一次模型调用 = 多 1 秒左右的首字延迟，而分流发生在最前面，用户感知最明显；
- 售后/导购的高频表达其实很固定（"能退吗""推荐个"），关键词覆盖已经够用；
- 规则是确定性的，调试和回归都容易；模型分类偶尔会把"能退吗"判成导购。

平票时的优先级是 政策 > 订单 > 导购：
"帮我推荐一款能退货的"同时命中两边，按政策回答更稳妥（有条款依据）。
"""

from __future__ import annotations

from enum import Enum


class Intent(str, Enum):
    ORDER = "order"
    POLICY = "policy"
    SHOPPING = "shopping"
    CHITCHAT = "chitchat"

    @property
    def label(self) -> str:
        return {
            Intent.ORDER: "订单售后",
            Intent.POLICY: "售后政策",
            Intent.SHOPPING: "商品导购",
            Intent.CHITCHAT: "闲聊",
        }[self]


# 关键词表：命中越多分数越高；"退""换"这种单字是为了覆盖"能退吗""想换个"
_RULES: list[tuple[Intent, tuple[str, ...]]] = [
    (
        Intent.POLICY,
        (
            "退", "换", "保修", "发票", "运费", "售后", "政策",
            "拆封", "七天", "无理由", "赔付", "质保", "开票",
        ),
    ),
    (
        Intent.ORDER,
        (
            "订单", "物流", "快递", "发货", "到货", "签收", "取消订单",
            "订单号", "我的单", "配送", "买了什么",
        ),
    ),
    (
        Intent.SHOPPING,
        (
            "推荐", "想买", "买个", "买什么", "有卖", "有没有", "哪个好",
            "帮我挑", "选一个", "价格", "便宜", "预算", "性价比", "送礼", "适合",
        ),
    ),
]

# 平票时的优先级
_PRIORITY = (Intent.POLICY, Intent.ORDER, Intent.SHOPPING)


def classify_intent(message: str) -> tuple[Intent, str]:
    """返回 (意图, 命中的关键词)；没命中任何规则就是闲聊。"""
    text = (message or "").strip().lower()
    if not text:
        return Intent.CHITCHAT, ""

    scores: dict[Intent, int] = {}
    first_hit: dict[Intent, str] = {}
    for intent, words in _RULES:
        hits = [w for w in words if w in text]
        if hits:
            scores[intent] = len(hits)
            first_hit[intent] = hits[0]

    if not scores:
        return Intent.CHITCHAT, ""

    best = max(scores.values())
    for intent in _PRIORITY:
        if scores.get(intent) == best:
            return intent, first_hit[intent]
    return Intent.CHITCHAT, ""
