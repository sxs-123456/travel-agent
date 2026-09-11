// 与后端 backend/models/rag.py 对齐的 RAG 问答类型定义。
export interface RagSource {
  source: string;
  snippet: string;
  score?: number | null;
}

export interface RagQueryResponse {
  answer: string;
  sources: RagSource[];
  /** true=来自本地知识库（带引用）；false=知识库未收录，由模型基于通用知识作答 */
  from_kb?: boolean;
}
