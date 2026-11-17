"""意图识别的单元测试（纯规则，不依赖模型 / 网络）。"""

from __future__ import annotations

from app.agents.intent import Intent, classify_intent


def test_policy_questions_route_to_policy():
    for message in ["耳机拆封了还能退吗", "保修多久", "能开发票吗", "退货运费谁承担", "想换个尺码"]:
        intent, _ = classify_intent(message)
        assert intent is Intent.POLICY, message


def test_order_questions_route_to_order():
    for message in ["我的订单到哪了", "什么时候发货", "快递单号是多少", "最近的订单状态"]:
        intent, _ = classify_intent(message)
        assert intent is Intent.ORDER, message


def test_shopping_questions_route_to_shopping():
    for message in ["推荐一款适合送礼的包", "想买个便宜点的行李箱", "有没有性价比高的手机", "预算五百买什么好"]:
        intent, _ = classify_intent(message)
        assert intent is Intent.SHOPPING, message


def test_cancel_order_goes_to_order_not_policy():
    """「取消订单」同时含"订单"，必须走订单而不是被"退"字带偏。"""
    intent, matched = classify_intent("帮我把订单 123 取消")
    assert intent is Intent.ORDER
    assert matched


def test_greeting_is_chitchat():
    intent, matched = classify_intent("你好")
    assert intent is Intent.CHITCHAT
    assert matched == ""


def test_empty_message_is_chitchat():
    assert classify_intent("")[0] is Intent.CHITCHAT


def test_tie_prefers_policy():
    """同时命中"推荐"和"退"时按政策处理，因为政策有条款依据，答错代价更小。"""
    intent, _ = classify_intent("帮我推荐一款能退货的包")
    assert intent is Intent.POLICY


def test_intent_labels_are_chinese():
    assert Intent.POLICY.label == "售后政策"
    assert Intent.SHOPPING.label == "商品导购"
