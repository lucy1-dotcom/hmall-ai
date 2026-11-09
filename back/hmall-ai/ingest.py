"""把政策文档灌进 Milvus（RAG 的离线入库步骤）。

用法：
    # 1. 先配好 key
    set SILICONFLOW_API_KEY=sk-xxxx          （Windows）
    export SILICONFLOW_API_KEY=sk-xxxx       （Linux/macOS）

    # 2. 入库
    python ingest.py
    python ingest.py --file policy.txt --chunk-size 500 --overlap 50
    python ingest.py --drop                  # 先删集合再重建（改了切块参数时用）

流程：读文件 -> 按句子切块（默认 500 字/块，重叠 50）-> 调 bge-m3 向量化
      -> 写入 Milvus 集合 hmall_policy。

幂等：id 取文本的 md5，重复执行不会产生重复数据，只会覆盖同内容的块。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from app.core.config import settings
from app.crud.milvus import MilvusRepository
from app.services.embeddings import EmbeddingError, embed_texts_sync
from app.utils.text import chunk_text


def make_id(text: str) -> str:
    """内容寻址：同样的文本永远得到同样的 id，便于覆盖更新。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把政策文档切块、向量化并写入 Milvus")
    parser.add_argument("--file", default=settings.policy_file, help="政策文档路径")
    parser.add_argument("--chunk-size", type=int, default=500, help="每块字符数")
    parser.add_argument("--overlap", type=int, default=50, help="块间重叠字符数")
    parser.add_argument("--batch-size", type=int, default=16, help="每次请求 embedding 的条数")
    parser.add_argument("--drop", action="store_true", help="先删除同名集合再重建")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"[错误] 找不到文件：{path.resolve()}")
        return 1

    text = path.read_text(encoding="utf-8")
    chunks = chunk_text(text, chunk_size=args.chunk_size, overlap=args.overlap)
    if not chunks:
        print("[错误] 文档内容为空，没有可入库的文本")
        return 1

    print(f"文件：{path}（{len(text)} 字）")
    print(f"切块：chunk_size={args.chunk_size} overlap={args.overlap} -> {len(chunks)} 块")
    for i, chunk in enumerate(chunks[:3], 1):
        preview = chunk.replace("\n", " ")[:60]
        print(f"  第{i}块预览（{len(chunk)} 字）：{preview}…")
    if len(chunks) > 3:
        print(f"  …… 其余 {len(chunks) - 3} 块省略")

    try:
        print(f"向量化：模型 {settings.embedding_model}，接口 {settings.siliconflow_base_url}")
        vectors = embed_texts_sync(chunks, batch_size=args.batch_size)
    except EmbeddingError as exc:
        print(f"[错误] {exc}")
        print("       检查 SILICONFLOW_API_KEY 是否配置、网络是否可达 api.siliconflow.cn")
        return 1

    dim = len(vectors[0])
    print(f"向量维度：{dim}")

    repo = MilvusRepository(settings.policy_collection)
    if args.drop:
        print(f"删除已有集合：{settings.policy_collection}")
        repo.drop()
    repo.ensure_collection(dim)

    records = [
        {
            "id": make_id(chunk),
            "vector": vector,
            "text": chunk,
            "source": path.name,
            "chunk_index": index,
        }
        for index, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    written = repo.upsert(records)
    print(f"[完成] 写入 {written} 条向量到集合 {settings.policy_collection}")
    print("       可在 Agent 里问「拆封的手机能退吗」验证检索效果")
    return 0


if __name__ == "__main__":
    sys.exit(main())
