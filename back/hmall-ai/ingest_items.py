"""把商品灌进 Milvus，供商品语义搜索使用（向量检索的离线建索引步骤）。

用法：
    # 前置：item-service + 网关已启动，SILICONFLOW_API_KEY 已配置
    python ingest_items.py --limit 20000          # 先灌 2 万条试水
    python ingest_items.py                        # 全量
    python ingest_items.py --drop                 # 先删集合再重建（改过文本拼接方式时用）
    python ingest_items.py --start-page 120       # 断点续传：从第 120 页继续

流程：分页调 item-service 的 /items/page -> 拼「名称+品牌+类目+规格」-> bge-m3 向量化
      -> 写入 Milvus 集合 hmall_items（id 用商品 id，天然幂等）。

为什么要拼多个字段而不是只用商品名：
    用户搜"降噪耳机"时，商品名里可能只有"华为 FreeBuds 5"，
    品牌和类目能补上语义线索，召回率明显更好。

幂等：主键就是商品 id，重复执行只会覆盖，不会产生重复数据。
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from app.core.config import settings
from app.crud.milvus import MilvusRepository
from app.services.embeddings import EmbeddingError, embed_texts_sync
from app.services.item_client import ItemClient


def build_text(item: dict[str, Any]) -> str:
    """把商品的关键属性拼成一段可检索文本。

    bge-m3 的输入长度有限，截断到 300 字足够覆盖名称 + 品牌 + 类目 + 规格。

    注意 spec 字段是 JSON 字符串：空规格在库里存的是 "{}"，
    直接拼进去会变成 "商品名 华为 手机 {}" 这种噪声，所以要把空 JSON 过滤掉。
    """
    spec = str(item.get("spec") or "").strip()
    if spec in {"{}", "[]", "null", "None"}:
        spec = ""
    parts = [
        item.get("name"),
        item.get("brand"),
        item.get("category"),
        spec,
    ]
    return " ".join(str(p).strip() for p in parts if p and str(p).strip())[:300]


def to_record(item: dict[str, Any], vector: list[float], text: str) -> dict[str, Any]:
    """转成 Milvus 记录：主键是商品 id，其余字段走动态字段（JSON）。"""
    item_id = str(item.get("id"))
    return {
        "id": item_id,
        "vector": vector,
        "text": text,
        # item_id 单独存一份：政策库用 text 做片段，商品库这里方便统一读取
        "item_id": item_id,
        "name": item.get("name") or "",
        "price": int(item.get("price") or 0),
        "image": item.get("image") or "",
        "category": item.get("category") or "",
        "brand": item.get("brand") or "",
        "stock": int(item.get("stock") or 0),
    }


def embed_page_safely(
    pairs: list[tuple[dict[str, Any], str]], batch_size: int
) -> tuple[list[list[float]], list[tuple[dict[str, Any], str]]]:
    """整页批量向量化；整批失败时逐条重试，跳过坏数据。

    真实数据里总有个别商品的文本会让接口返回 400（超长、特殊字符等）。
    如果整页失败就退出，几十万条数据要重跑很多次，
    所以这里退化成「一条一条来」，坏的那条跳过并打印出来。
    """
    try:
        vectors = embed_texts_sync([text for _, text in pairs], batch_size=batch_size)
        return vectors, pairs
    except EmbeddingError as exc:
        print(f"  [警告] 整页向量化失败（{exc}），改为逐条重试")

    vectors: list[list[float]] = []
    kept: list[tuple[dict[str, Any], str]] = []
    for item, text in pairs:
        try:
            vector = embed_texts_sync([text], batch_size=1)[0]
        except EmbeddingError:
            print(f"  [跳过] id={item.get('id')} 文本无法向量化：{text[:40]}")
            continue
        vectors.append(vector)
        kept.append((item, text))
    return vectors, kept


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把商品向量化并写入 Milvus")
    parser.add_argument(
        "--base-url",
        default=settings.hmall_gateway_url,
        help="商品服务地址（默认走网关，也可直连 item-service:8081）",
    )
    parser.add_argument("--page-size", type=int, default=100, help="每页拉取条数")
    parser.add_argument("--batch-size", type=int, default=32, help="每次请求 embedding 的条数")
    parser.add_argument("--limit", type=int, default=0, help="最多灌多少条（0=全量）")
    parser.add_argument("--start-page", type=int, default=1, help="从第几页开始（断点续传）")
    parser.add_argument("--drop", action="store_true", help="先删除集合再重建")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = ItemClient(args.base_url)

    # 先探一页，拿到总页数，顺便尽早暴露"服务没起来"这类问题
    try:
        first = client.list_items_page(1, args.page_size)
    except Exception as exc:  # noqa: BLE001 - 离线脚本，失败就打印人话
        print(f"[错误] 拉取商品失败：{exc}")
        print(f"       检查 {args.base_url} 是否可达（网关 8080 / item-service 8081）")
        return 1

    total = int(first.get("total") or 0)
    pages = int(first.get("pages") or 0) or max(1, (total + args.page_size - 1) // args.page_size)
    print(f"商品总数：{total}，共 {pages} 页（page_size={args.page_size}）")

    repo = MilvusRepository(settings.milvus_collection)
    if args.drop:
        print(f"删除已有集合：{settings.milvus_collection}")
        repo.drop()

    written = 0
    started = time.time()
    ensured = False

    for page_no in range(args.start_page, pages + 1):
        # 第 1 页已经拉过了，复用它省一次请求；续传时其余页重新拉
        page = first if page_no == 1 else client.list_items_page(page_no, args.page_size)
        items = [it for it in (page.get("list") or []) if it and it.get("id")]

        # 拼文本 -> 过滤空文本
        pairs = [(it, build_text(it)) for it in items]
        pairs = [(it, text) for it, text in pairs if text]
        if not pairs:
            continue

        vectors, pairs = embed_page_safely(pairs, args.batch_size)
        if not pairs:
            print(f"  [跳过] 第 {page_no} 页全部向量化失败")
            continue

        # 集合在第一次拿到真实维度后创建一次即可，避免每页都发一次 has_collection
        if not ensured:
            repo.ensure_collection(len(vectors[0]))
            ensured = True
        records = [to_record(it, vec, text) for (it, text), vec in zip(pairs, vectors)]
        repo.upsert(records)
        written += len(records)

        if page_no % 10 == 0 or page_no == pages:
            elapsed = time.time() - started
            speed = written / elapsed if elapsed > 0 else 0
            print(
                f"  第 {page_no}/{pages} 页，累计 {written} 条，"
                f"{speed:.1f} 条/秒，用时 {elapsed:.0f}s"
            )

        if args.limit and written >= args.limit:
            print(f"已达到上限 {args.limit} 条，停止")
            break

    print(f"[完成] 写入 {written} 条向量到集合 {settings.milvus_collection}")
    print("       验证：POST /ai/search  {\"query\": \"降噪耳机\"}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
