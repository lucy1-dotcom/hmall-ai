"""混合检索的零件：BM25、RRF 融合、rerank。

为什么要混合检索：
- **纯向量**擅长语义（"耳机"能召回"蓝牙对耳"），但对**精确关键词**不敏感
  （条款编号、"四百-八百-八八八八"、"四十八小时"这类数字和专有名词容易被稀释）；
- **BM25** 正好相反，字面命中强、语义弱；
- 两者用 **RRF（Reciprocal Rank Fusion）** 融合：只看排名不看分数，
  不需要把两套打分归一化，工程上最省心。

为什么还要 rerank：
向量和 BM25 都是"粗排"，各自召回 10 条后用一个 cross-encoder 模型
（bge-reranker）对「query-文档」逐对打分，精度明显更高，代价是慢（几十毫秒级），
所以只对少量候选做，不做全量。
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from typing import Iterable, Sequence

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_ASCII_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """中英文混合分词：英文数字按词，中文按字符 bigram。

    不引入 jieba：一来少一个依赖，二来知识库规模很小（几十个块），
    bigram 对中文的召回已经够用，而且对"条款编号""数字"这类短串更稳。
    """
    text = (text or "").lower()
    tokens = _ASCII_RE.findall(text)
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
            continue
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


class BM25Index:
    """极简 BM25（k1=1.5, b=0.75）。"""

    def __init__(self, docs: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs = list(docs)
        self.tfs: list[Counter[str]] = [Counter(tokenize(d)) for d in self.docs]
        self.doc_len = [sum(tf.values()) for tf in self.tfs]
        self.n = len(self.docs)
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0

        df: Counter[str] = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        self.idf = {
            term: math.log(1 + (self.n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """返回 [(文档下标, 分数)]，按分数降序，过滤 0 分。"""
        terms = tokenize(query)
        scored: list[tuple[int, float]] = []
        for idx, tf in enumerate(self.tfs):
            score = 0.0
            for term in terms:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                idf = self.idf.get(term, 0.0)
                denom = freq + self.k1 * (1 - self.b + self.b * self.doc_len[idx] / (self.avgdl or 1))
                score += idf * freq * (self.k1 + 1) / denom
            if score > 0:
                scored.append((idx, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def rrf_fuse(
    rankings: Iterable[Sequence[str]],
    k: int = 60,
    top_k: int = 10,
    weights: Sequence[float] | None = None,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion：score(d) = Σ w_i / (k + rank_i)。

    只看排名不看原始分数，所以不用关心"余弦相似度 0.7"和"BM25 12.3"怎么换算。
    weights 用来调两路的权重：中文 bigram 的 BM25 噪声偏大，
    实测给向量更高权重（BM25 0.5）比等权更稳。
    """
    scores: dict[str, float] = defaultdict(float)
    for path, ranking in enumerate(rankings):
        weight = weights[path] if weights and path < len(weights) else 1.0
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] += weight * (1.0 / (k + rank))
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ordered[:top_k]


class RerankError(RuntimeError):
    """rerank 服务不可用。"""


async def rerank(
    query: str,
    documents: Sequence[str],
    *,
    top_n: int | None = None,
    timeout: float = 30.0,
) -> list[tuple[int, float]]:
    """调 bge-reranker 对候选文档重排，返回 [(原下标, 相关度)]。

    失败时抛 RerankError，调用方降级为融合顺序（不能因为重排挂了就整个检索挂掉）。
    """
    if not documents:
        return []
    if not settings.siliconflow_api_key:
        raise RerankError("未配置 SILICONFLOW_API_KEY，无法调用 rerank")

    url = f"{settings.siliconflow_base_url.rstrip('/')}/rerank"
    payload = {
        "model": settings.rerank_model,
        "query": query,
        "documents": list(documents),
        "top_n": top_n or len(documents),
    }
    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise RerankError(f"请求 rerank 失败: {exc}") from exc

    if resp.status_code != 200:
        raise RerankError(f"rerank 接口返回 {resp.status_code}: {resp.text[:200]}")

    results = (resp.json() or {}).get("results") or []
    pairs = [(int(r.get("index", -1)), float(r.get("relevance_score", 0.0))) for r in results]
    return [p for p in pairs if p[0] >= 0]
