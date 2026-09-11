"""旅行知识库 RAG 模块（本地向量检索，免 key、免部署）。

提供「先检索、后生成」的检索增强问答能力：
  1. 文档切块 → 本地 Embedding（sentence-transformers）→ 存入 Chroma 向量库；
  2. 提问时向量检索 top-k 相关片段；
  3. 组装 prompt（附引用来源）→ 交给 LLM 生成有据可查的回答。

依赖（可选，不装也不影响主流程，见 requirements-rag.txt）：
  pip install -r requirements-rag.txt
"""
from backend.rag.query import query_knowledge, RagUnavailableError
from backend.rag.ingest import ingest_documents

__all__ = ["query_knowledge", "ingest_documents", "RagUnavailableError"]
