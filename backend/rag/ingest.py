"""文档入库（ingest）：读取知识库 markdown → 切块 → 向量化 → 写入 Chroma。

可重复执行：同一文档按稳定 id 去重（重新入库会覆盖旧版本）。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from backend.rag.chunking import split_text
from backend.rag.embedding import embed_texts
from backend.rag.store import clear, upsert_chunks

logger = logging.getLogger("trip-planner")

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _slugify(text: str) -> str:
    """把文档名归一化为稳定的 id 前缀（去掉扩展名与非字母数字）。"""
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", text).strip("_")


def _load_documents(data_dir: Path | None = None) -> list[tuple[str, str]]:
    """读取目录下所有 .md 文件，返回 [(文件名, 内容)]。"""
    data_dir = data_dir or _DATA_DIR
    docs = []
    for f in sorted(data_dir.glob("*.md")):
        docs.append((f.name, f.read_text(encoding="utf-8")))
    return docs


def ingest_documents(data_dir: Path | None = None,
                     chunk_size: int = 200, overlap: int = 40) -> int:
    """把知识库文档切块、向量化并写入 Chroma，返回入库 chunk 总数。

    全量重建：先清空向量库再写入，保证编辑/新增文档后不会残留旧 chunk。
    数据为空时返回 0（不报错），调用方可据此判断是否需要先准备文档。
    """
    docs = _load_documents(data_dir)
    if not docs:
        logger.warning("知识库目录为空：%s", data_dir or _DATA_DIR)
        return 0

    clear()  # 全量重建
    ids: list[str] = []
    texts: list[str] = []
    metas: list[dict] = []
    for doc_name, content in docs:
        prefix = _slugify(doc_name)
        for i, chunk in enumerate(split_text(content, chunk_size, overlap)):
            ids.append(f"{prefix}#{i}")
            texts.append(chunk)
            metas.append({"source": doc_name, "chunk_index": i})

    embeddings = embed_texts(texts)
    upsert_chunks(ids, texts, embeddings, metas)
    logger.info("知识库入库完成：%d 个 chunk（%d 篇文档）", len(ids), len(docs))
    return len(ids)


if __name__ == "__main__":
    # 允许直接运行：python -m backend.rag.ingest [--dir 知识库目录]
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    import argparse

    parser = argparse.ArgumentParser(description="把知识库文档切块、向量化并写入 Chroma")
    parser.add_argument("--dir", default=None, help="知识库目录，默认 backend/rag/data")
    args = parser.parse_args()
    count = ingest_documents(Path(args.dir) if args.dir else None)
    print(f"入库完成：{count} 个 chunk")
