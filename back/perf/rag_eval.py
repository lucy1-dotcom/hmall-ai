"""RAG 检索策略评测：纯向量 vs 混合检索 vs 混合+rerank。

指标：
- **Recall@3**：正确答案是否出现在前 3 条里
- **MRR@10**：第一条正确结果的排名倒数（第 1 名 = 1.0，第 5 名 = 0.2），
  比 Recall 更敏感，能区分"排第 1"和"排第 3"
- **平均耗时**：包含 embedding + Milvus + BM25 + rerank 的端到端时间

用法：
    # 需要 Milvus 里已有政策知识库（ingest.py），且配好 SILICONFLOW_API_KEY
    python perf/rag_eval.py
    python perf/rag_eval.py --modes vector hybrid
    python perf/rag_eval.py --verbose          # 打印每条问题的排名，便于分析

评测集是 30 条人工整理的售后问题，每条对应知识库里**唯一**能回答它的那段条款，
用「答案关键词」判定是否命中（关键词取自该条款的独有表述）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "hmall-ai"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.policy import policy_store  # noqa: E402


@dataclass(frozen=True)
class Case:
    question: str
    keyword: str  # 正确答案里必然出现的关键词


CASES: list[Case] = [
    Case("耳机拆封了还能退吗", "耳机"),
    Case("手机开机激活后能退吗", "开机激活"),
    Case("定制商品能退货吗", "定制类商品"),
    Case("生鲜收到是坏的怎么办", "二十四小时"),
    Case("退款多久能到账", "三个工作日内发起"),
    Case("退货运费谁承担", "运费由用户承担"),
    Case("发票怎么开", "增值税专用发票"),
    Case("下单后多久发货", "四十八小时内发出"),
    Case("会员等级怎么升级", "近十二个月"),
    Case("优惠券可以叠加使用吗", "平台券与店铺券"),
    Case("换货运费谁出", "换货超过两次"),
    Case("大家电保修多久", "主要部件保修三年"),
    Case("化妆品拆封了能退吗", "已拆封的不支持"),
    Case("奶粉拆封能退吗", "奶粉"),
    Case("对处理结果不满意怎么办", "平台介入复核"),
    Case("客服工作时间是几点到几点", "九点至二十一点"),
    Case("拒收商品运费谁付", "拒收"),
    Case("还没发货能改收货地址吗", "修改收货地址"),
    Case("退货后满减优惠会扣回吗", "满减门槛"),
    Case("发票金额包含优惠券吗", "实付金额"),
    Case("大家电由谁负责安装", "指定服务商"),
    Case("衣服吊牌剪了还能退吗", "吊牌完整"),
    Case("鞋子穿过还能退吗", "鞋底无明显磨损"),
    Case("临期商品算质量问题吗", "临期商品"),
    Case("婴儿车支持七天无理由吗", "安全座椅"),
    Case("恶意投诉会怎么处理", "伪造证据"),
    Case("港澳台地区发货吗", "港澳台"),
    Case("电子发票多久能开出来", "一个工作日内开具"),
    Case("生鲜商品怎么赔付", "按比例或全额退款"),
    Case("超过十五天还能退货吗", "厂家保修政策"),
]


async def run_mode(mode: str, top_k: int, verbose: bool) -> dict:
    settings.policy_retrieval_mode = mode
    recall1 = 0
    recallk = 0
    rr_sum = 0.0
    latencies: list[float] = []
    misses: list[tuple[str, str, int | None]] = []

    for case in CASES:
        started = time.perf_counter()
        rows = await policy_store.search(case.question, top_k=top_k)
        latencies.append((time.perf_counter() - started) * 1000)

        texts = [str(r.get("text") or "") for r in rows]
        rank = next((i + 1 for i, text in enumerate(texts) if case.keyword in text), None)

        if rank == 1:
            recall1 += 1
        if rank is not None:
            recallk += 1
        rr_sum += 1.0 / rank if rank else 0.0
        if rank != 1:
            misses.append((case.question, case.keyword, rank))
        if verbose:
            print(f"    {mode:<14} rank={str(rank):<5} {case.question}")

    total = len(CASES)
    return {
        "mode": mode,
        "recall@1": recall1 / total,
        "recall@k": recallk / total,
        "mrr": rr_sum / total,
        "avg_ms": sum(latencies) / len(latencies),
        "misses": misses,
    }


def check_keywords_covered() -> list[str]:
    """自检：评测集里的关键词必须真的出现在知识库里，否则这条用例没有意义。"""
    policy_store._ensure_bm25()  # noqa: SLF001 - 评测脚本，直接读内部缓存
    corpus = "\n".join(str(r.get("text") or "") for r in policy_store._chunks)  # noqa: SLF001
    return [c.keyword for c in CASES if c.keyword not in corpus]


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 检索策略评测")
    parser.add_argument("--modes", nargs="+", default=["vector", "hybrid", "hybrid_rerank"])
    parser.add_argument("--top-k", type=int, default=3, help="和 Agent 实际取用的块数一致")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    missing = check_keywords_covered()
    if missing:
        print(f"[警告] 以下关键词在知识库里找不到，对应用例永远无法命中：{missing}\n")

    print(f"评测集 {len(CASES)} 条，知识库 {len(policy_store._chunks)} 块，每问取 {args.top_k} 块\n")  # noqa: SLF001

    results = []
    for mode in args.modes:
        print(f"跑 {mode} ...")
        results.append(asyncio.run(run_mode(mode, args.top_k, args.verbose)))

    print()
    print(f"{'模式':<16}{'Recall@1':>10}{'Recall@3':>10}{'MRR':>8}{'平均ms':>10}")
    print("-" * 54)
    for r in results:
        print(f"{r['mode']:<16}{r['recall@1']:>9.1%}{r['recall@k']:>10.1%}{r['mrr']:>8.3f}{r['avg_ms']:>10.1f}")

    if len(results) > 1:
        base = results[0]
        best = max(results, key=lambda x: (x["recall@1"], x["mrr"]))
        print()
        print(f"最好的是 {best['mode']}：Recall@1 {base['recall@1']:.1%} -> {best['recall@1']:.1%}，"
              f"MRR {base['mrr']:.3f} -> {best['mrr']:.3f}")

    base_misses = {(m[0], m[1]) for m in results[0]["misses"]} if results else set()
    last_misses = {(m[0], m[1]) for m in results[-1]["misses"]} if results else set()
    fixed = sorted(base_misses - last_misses)
    if fixed:
        print(f"\n{results[0]['mode']} 没排第一、{results[-1]['mode']} 排到第一的 {len(fixed)} 条：")
        for question, _ in fixed:
            print(f"  · {question}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
