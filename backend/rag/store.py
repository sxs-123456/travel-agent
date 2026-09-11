"""轻量向量库（纯 Python + numpy，免编译、免部署、免外部服务）。

设计取舍：
- 演示/中小规模知识库用「余弦相似度暴力检索」已足够快，且零运维、零编译；
  chromadb 依赖 chroma-hnswlib（需 MSVC 编译），faiss 依赖 C++ 扩展，均非纯 Python；
- 向量与元数据落盘为 .npy + JSON，进程重启不丢；
- 对外接口（upsert / search）与 Chroma 对齐，生产可直接换成 Chroma / FAISS / Milvus。

检索语义：embedding 已归一化（normalize_embeddings=True），
余弦相似度退化为点积；返回的 distance = 1 - 相似度（越小越相似，与 Chroma 一致）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("trip-planner")


def _numpy():
    """懒加载 numpy：未安装时给出清晰提示，不影响主流程 import。"""
    try:
        import numpy as np
    except ImportError as exc:  # noqa: BLE001
        raise RuntimeError(
            "未安装 numpy，无法使用向量库。请先执行：pip install -r requirements-rag.txt"
        ) from exc
    return np


def _db_path() -> Path:
    """向量库落盘目录（项目根 .vectordb，已加入 .gitignore）。"""
    root = Path(__file__).resolve().parent.parent.parent
    return root / ".vectordb"


def clear() -> None:
    """清空向量库落盘数据（全量重建时调用，避免编辑文档后残留旧 chunk）。"""
    p = _db_path()
    for f in (p / "vectors.npy", p / "meta.json"):
        try:
            f.unlink()
        except FileNotFoundError:
            pass


def _load():
    """读取已持久化的 (ids, texts, metas, vectors)；空库返回空序列 + 空数组。"""
    np = _numpy()
    p = _db_path()
    vp, mp = p / "vectors.npy", p / "meta.json"
    if not (vp.exists() and mp.exists()):
        return [], [], [], np.empty((0, 0), dtype=np.float32)
    with open(mp, encoding="utf-8") as f:
        d = json.load(f)
    return d["ids"], d["texts"], d["metas"], np.load(vp)


def _save(ids, texts, metas, vectors) -> None:
    np = _numpy()
    p = _db_path()
    p.mkdir(parents=True, exist_ok=True)
    np.save(p / "vectors.npy", vectors)
    with open(p / "meta.json", "w", encoding="utf-8") as f:
        json.dump({"ids": ids, "texts": texts, "metas": metas}, f, ensure_ascii=False)


def upsert_chunks(ids: list[str], texts: list[str], embeddings: list[list[float]],
                  metas: list[dict]) -> None:
    """写入/覆盖一批 chunk（按 id 去重，重复 id 覆盖旧数据）。"""
    np = _numpy()
    old_ids, old_texts, old_metas, old_vecs = _load()
    id_to_idx = {cid: i for i, cid in enumerate(old_ids)}

    merged_ids = list(old_ids)
    merged_texts = list(old_texts)
    merged_metas = list(old_metas)
    merged_vecs = [old_vecs[i] for i in range(len(old_ids))] if old_vecs.size else []

    for cid, text, meta, emb in zip(ids, texts, metas, embeddings):
        vec = np.asarray(emb, dtype=np.float32)
        if cid in id_to_idx:
            i = id_to_idx[cid]
            merged_texts[i], merged_metas[i], merged_vecs[i] = text, meta, vec
        else:
            id_to_idx[cid] = len(merged_ids)
            merged_ids.append(cid)
            merged_texts.append(text)
            merged_metas.append(meta)
            merged_vecs.append(vec)

    vectors = np.stack(merged_vecs).astype(np.float32) if merged_vecs else np.empty((0, 0), dtype=np.float32)
    _save(merged_ids, merged_texts, merged_metas, vectors)
    logger.info("向量库写入 %d 个 chunk", len(merged_ids))


def search(query_embedding: list[float], top_k: int = 4) -> dict:
    """按查询向量检索 top_k 个最相似片段。

    返回与 Chroma query 一致的形状：
      {"documents": [[...]], "metadatas": [[...]], "distances": [[...]]}
    """
    np = _numpy()
    _ids, texts, metas, vectors = _load()
    if vectors.size == 0:
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

    q = np.asarray(query_embedding, dtype=np.float32)
    sims = vectors @ q  # 归一化向量点积 = 余弦相似度
    top_k = min(top_k, len(texts))
    idx = np.argsort(-sims)[:top_k]

    docs = [texts[i] for i in idx]
    dists = [float(1 - sims[i]) for i in idx]
    metas_out = [dict(metas[i]) for i in idx]
    return {"documents": [docs], "metadatas": [metas_out], "distances": [dists]}
