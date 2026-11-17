"""混合检索组件的单元测试（不依赖网络 / Milvus）。"""

from __future__ import annotations

import asyncio

import pytest

from app.services.retrieval import BM25Index, RerankError, rerank, rrf_fuse, tokenize


def test_tokenize_mixes_chinese_bigram_and_ascii():
    tokens = tokenize("七天无理由退货（7 days）")
    assert "七天" in tokens          # 中文 bigram
    assert "天无" in tokens
    assert "7" in tokens             # 数字按词
    assert "days" in tokens


def test_tokenize_single_cjk_char():
    assert tokenize("退") == ["退"]


def test_bm25_ranks_matching_document_first():
    docs = [
        "七天无理由退货的运费由用户承担。",
        "生鲜商品需在签收后二十四小时内申请售后。",
        "会员按近十二个月累计实付金额升级。",
    ]
    index = BM25Index(docs)

    hits = index.search("运费谁承担", top_k=3)

    assert hits, "应该至少命中一条"
    assert docs[hits[0][0]] == docs[0]


def test_bm25_returns_empty_when_nothing_matches():
    index = BM25Index(["发票", "运费"])
    assert index.search("会员等级") == []


def test_rrf_fuse_rewards_documents_appearing_in_both_lists():
    # doc "c" 在两路里都排第 2，应该比只在一路里排第 1 的 "a" 更靠前
    fused = rrf_fuse([["a", "c"], ["b", "c"]], k=60, top_k=3)
    assert [doc for doc, _ in fused][0] == "c"


def test_rrf_weights_shift_ranking():
    # 各自排第一时等权打分相同；把第一路权重拉高后 a 胜出
    equal = dict(rrf_fuse([["a", "x"], ["b", "y"]], weights=[1.0, 1.0]))
    weighted = dict(rrf_fuse([["a", "x"], ["b", "y"]], weights=[10.0, 0.5]))
    assert equal["a"] == equal["b"]
    assert weighted["a"] > weighted["b"]


def test_rerank_without_key_raises():
    from app.core.config import settings

    original = settings.siliconflow_api_key
    settings.siliconflow_api_key = ""
    try:
        with pytest.raises(RerankError):
            asyncio.run(rerank("耳机能退吗", ["耳机拆封不支持退货", "运费由用户承担"]))
    finally:
        settings.siliconflow_api_key = original


def test_rerank_empty_documents_returns_empty():
    assert asyncio.run(rerank("任意问题", [])) == []
