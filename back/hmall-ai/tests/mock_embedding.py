"""测试用：模拟硅基流动的 /v1/embeddings 接口。

没有 SILICONFLOW_API_KEY 时，用它把 RAG 链路跑通：

    python tests/mock_embedding.py 8097
    set SILICONFLOW_BASE_URL=http://127.0.0.1:8097/v1
    set SILICONFLOW_API_KEY=test
    python ingest.py --drop

实现方式：把文本拆成字符 bigram，用 md5 哈希到 1024 维再归一化。
它没有真正的语义能力，但“字面重合度高”的文本向量也相近，
足以验证 切块 -> 向量 -> Milvus -> 检索 这条链路是通的。
真实的语义检索效果请配置 bge-m3（也就是配好 SILICONFLOW_API_KEY）。

和 pytest 的关系：文件名不以 test_ 开头，pytest 不会收集它；
它只是一个手动启动的本地 HTTP 服务。
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

DIM = 1024


def embed(text: str) -> list[float]:
    """字符 bigram 哈希成 1024 维，再 L2 归一化（配合 COSINE 距离）。"""
    vec = [0.0] * DIM
    text = text.strip()
    for i in range(len(text) - 1):
        gram = text[i : i + 2]
        h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
        vec[h % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - 覆盖基类方法
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        texts = body.get("input") or []
        if isinstance(texts, str):
            texts = [texts]

        payload = {
            "object": "list",
            "model": body.get("model", "BAAI/bge-m3"),
            "data": [
                {"object": "embedding", "index": i, "embedding": embed(t)}
                for i, t in enumerate(texts)
            ],
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args) -> None:  # 静音，别刷屏
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8097
    print(f"mock embedding server on http://127.0.0.1:{port}/v1 (dim={DIM})")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
