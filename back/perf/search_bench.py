"""对比「MySQL LIKE 关键词搜索」与「Milvus 向量语义搜索」的延迟。

用法：
    # 两个服务都起来后跑
    python perf/search_bench.py --n 30 --query 降噪耳机

    # 只测一边
    python perf/search_bench.py --skip-keyword
    python perf/search_bench.py --skip-vector

默认目标：
    关键词  http://127.0.0.1:8080/search/list   （走网关到 item-service，LIKE '%key%'）
    语义    http://127.0.0.1:8000/ai/search      （走 Python AI 服务，Milvus 向量检索）

注意：语义搜索是 POST + JSON；关键词搜索是 GET + query 参数。
两边都取 10 条，保证比较公平。
"""

from __future__ import annotations

import argparse
import statistics
import time

import httpx


def percentile(values: list[float], p: float) -> float:
    """线性插值求分位数（样本量小时比 nearest 更稳）。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    low, high = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (k - low)


def bench_keyword(url: str, query: str, n: int, size: int) -> tuple[list[float], int]:
    latencies: list[float] = []
    count = 0
    with httpx.Client(timeout=30) as client:
        for _ in range(n):
            start = time.perf_counter()
            resp = client.get(url, params={"key": query, "pageNo": 1, "pageSize": size})
            resp.raise_for_status()
            latencies.append((time.perf_counter() - start) * 1000)
            data = resp.json()
            count = len((data or {}).get("list") or [])
    return latencies, count


def bench_vector(url: str, query: str, n: int, size: int) -> tuple[list[float], int]:
    latencies: list[float] = []
    count = 0
    with httpx.Client(timeout=30) as client:
        for _ in range(n):
            start = time.perf_counter()
            resp = client.post(url, json={"query": query, "top_k": size})
            resp.raise_for_status()
            latencies.append((time.perf_counter() - start) * 1000)
            data = resp.json()
            count = len((data or {}).get("hits") or [])
    return latencies, count


def report(name: str, latencies: list[float], count: int) -> None:
    if not latencies:
        print(f"{name:<10} 无数据")
        return
    print(
        f"{name:<10} n={len(latencies):<3} 命中={count:<3} "
        f"avg={statistics.mean(latencies):7.1f}ms "
        f"p50={percentile(latencies, 0.50):7.1f}ms "
        f"p95={percentile(latencies, 0.95):7.1f}ms "
        f"p99={percentile(latencies, 0.99):7.1f}ms "
        f"max={max(latencies):7.1f}ms"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="关键词搜索 vs 向量语义搜索 延迟对比")
    parser.add_argument("--keyword-url", default="http://127.0.0.1:8080/search/list")
    parser.add_argument("--vector-url", default="http://127.0.0.1:8000/ai/search")
    parser.add_argument("--query", default="降噪耳机")
    parser.add_argument("--n", type=int, default=30, help="每边请求次数")
    parser.add_argument("--size", type=int, default=10, help="返回条数")
    parser.add_argument("--skip-keyword", action="store_true")
    parser.add_argument("--skip-vector", action="store_true")
    args = parser.parse_args()

    print(f"查询词：{args.query}  每边 {args.n} 次  返回 {args.size} 条\n")

    # 预热一次，避免第一次请求的建连/编译开销污染统计
    try:
        if not args.skip_keyword:
            bench_keyword(args.keyword_url, args.query, 1, args.size)
        if not args.skip_vector:
            bench_vector(args.vector_url, args.query, 1, args.size)
    except Exception as exc:  # noqa: BLE001
        print(f"[警告] 预热失败（可能是服务没起来）：{exc}\n")

    if not args.skip_keyword:
        try:
            latencies, count = bench_keyword(args.keyword_url, args.query, args.n, args.size)
            report("关键词搜索", latencies, count)
        except Exception as exc:  # noqa: BLE001
            print(f"[错误] 关键词搜索失败：{exc}")

    if not args.skip_vector:
        try:
            latencies, count = bench_vector(args.vector_url, args.query, args.n, args.size)
            report("语义搜索", latencies, count)
        except Exception as exc:  # noqa: BLE001
            print(f"[错误] 语义搜索失败：{exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
