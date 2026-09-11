"""文档切块（chunking）：把长文档切成带重叠的文本块。

RAG 的召回质量很大程度上取决于切块：
- 块太大 → 检索噪声多、上下文超出模型窗口；
- 块太小 → 语义碎片化、丢失上下文；
- 重叠（overlap）→ 避免关键句子恰好被切在两块之间。

这里用「先按句切分、再按目标长度合并」的句子感知切法，
比裸滑窗更能保住句子的完整性。
"""
from __future__ import annotations

import re

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*|\n+")


def split_text(text: str, chunk_size: int = 200, overlap: int = 40) -> list[str]:
    """把文本切成约 chunk_size 字、块间 overlap 字重叠的块。

    Args:
        text: 原始文本。
        chunk_size: 目标块长度（字符数）。
        overlap: 相邻块之间的重叠长度，应小于 chunk_size。

    Returns:
        文本块列表（可能为空）。
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    # 先按句切分（保留句末标点）
    sentences = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    if not sentences:
        return [text]

    chunks: list[str] = []
    cur = ""
    for s in sentences:
        if not cur:
            cur = s
        elif len(cur) + len(s) + 1 <= chunk_size:
            cur = f"{cur} {s}"
        else:
            chunks.append(cur)
            # 重叠：把当前块结尾的 overlap 字带入下一块起始
            cur = f"{cur[-overlap:]} {s}" if len(cur) > overlap else s
    if cur:
        chunks.append(cur)
    return chunks
