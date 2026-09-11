"""本地 Embedding（免 key、免部署）：懒加载单例。

使用 sentence-transformers 加载中文向量模型，首次调用时下载模型权重。
模型可通过 .env 的 EMBEDDING_MODEL 指定：
- 留空/默认：BAAI/bge-small-zh-v1.5（HuggingFace 在线下载）；
- 网络受限：先在有网机器 `huggingface-cli download` 或手动下载模型目录，
  再填本地路径（如 D:/models/bge-small-zh-v1.5），即可离线加载。

国内网络加速
------------
huggingface.co 在国内直连常超时（首次下载会反复重试几十秒）。
默认通过 HF_ENDPOINT 指向官方镜像 hf-mirror.com（免 key），可被 .env/环境变量覆盖。
"""
from __future__ import annotations

import logging
import os

from backend.config import settings

logger = logging.getLogger("trip-planner")

_DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
# HuggingFace 官方认可的国内镜像，免 key，国内可访问。
# 被 .env / 环境变量的 HF_ENDPOINT 覆盖；离线环境请设 EMBEDDING_MODEL 为本地路径。
_DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"

# 懒加载单例：只在实际用到时 import 并加载，避免拖慢主流程启动。
_embedder = None


class RagUnavailableError(RuntimeError):
    """RAG 依赖未安装时抛出，便于上层给出清晰提示。"""


def get_embedder():
    """返回共享的 SentenceTransformer 实例（懒加载）。"""
    global _embedder
    if _embedder is None:
        # 必须在 import sentence_transformers 之前设置 huggingface_hub 的镜像 endpoint，
        # 否则 sentence-transformers 启动时就会去 huggingface.co 校验 HEAD，超时。
        os.environ.setdefault("HF_ENDPOINT", _DEFAULT_HF_ENDPOINT)
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # noqa: BLE001
            raise RagUnavailableError(
                "未安装 sentence-transformers，无法使用本地 Embedding。"
                "请先执行：pip install -r requirements-rag.txt"
            ) from exc
        model = (settings.embedding_model or "").strip() or _DEFAULT_MODEL
        logger.info("加载向量模型 %s（首次会下载权重，HF_ENDPOINT=%s）...",
                    model, os.environ.get("HF_ENDPOINT", ""))
        try:
            _embedder = SentenceTransformer(model)
        except Exception as exc:  # noqa: BLE001
            raise RagUnavailableError(
                f"加载向量模型 {model} 失败：{exc}。"
                "在线下载可设 HF_ENDPOINT=https://hf-mirror.com 加速；"
                "网络受限可下载模型目录后，在 .env 配置 EMBEDDING_MODEL=本地路径。"
            ) from exc
    return _embedder


def embed_texts(texts: list[str]) -> list[list[float]]:
    """把若干文本编码为归一化向量，返回 list[list[float]]。"""
    if not texts:
        return []
    vecs = get_embedder().encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vecs]
