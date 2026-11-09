"""文本处理小工具（RAG 切块、截断）。"""

from __future__ import annotations

import re
from typing import Iterable, List

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
    """按句子边界切块，块之间保留 overlap 个字符的重叠，避免语义被切断。

    chunk_size 按字符数算（中文场景比 token 更直观），400 字符大约 200~300 token。
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    sentences = [s for s in _SENTENCE_SPLIT.split(text) if s]
    chunks: List[str] = []
    buffer = ""
    for sentence in sentences:
        if len(buffer) + len(sentence) <= chunk_size:
            buffer += sentence
            continue
        if buffer:
            chunks.append(buffer.strip())
            # 保留尾部 overlap，作为下一块的开头
            buffer = buffer[-overlap:] if overlap > 0 else ""
        buffer += sentence
        # 单句超长时硬切
        while len(buffer) > chunk_size:
            chunks.append(buffer[:chunk_size].strip())
            buffer = buffer[chunk_size - overlap:] if overlap > 0 else buffer[chunk_size:]
    if buffer.strip():
        chunks.append(buffer.strip())
    return [c for c in chunks if c]


def truncate(text: str | None, limit: int = 120) -> str | None:
    """截断长文本，用于生成摘要片段。"""
    if text is None:
        return None
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def join_context(chunks: Iterable[str], limit: int = 4000) -> str:
    """把多段知识拼成提示词上下文，总长度设上限防止超出模型窗口。"""
    parts: List[str] = []
    total = 0
    for chunk in chunks:
        if total + len(chunk) > limit:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)
