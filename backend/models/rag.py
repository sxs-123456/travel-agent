"""RAG 问答的 Pydantic 模型。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class RagQueryRequest(BaseModel):
    """知识库问答请求。"""

    question: str = Field(..., description="用户提问")
    top_k: int = Field(4, ge=1, le=10, description="检索片段数量")


class RagSource(BaseModel):
    """引用来源（命中片段 + 所属文档）。"""

    source: str = Field(..., description="来源文档名")
    snippet: str = Field("", description="命中片段摘要")
    score: Optional[float] = Field(None, description="相似度（1=最相似）")


class RagQueryResponse(BaseModel):
    """知识库问答响应：答案 + 引用来源。"""

    answer: str = Field(..., description="基于知识库生成的回答")
    sources: List[RagSource] = Field(default_factory=list, description="引用来源列表")
    from_kb: bool = Field(
        True,
        description="答案来源：True=来自本地知识库（带引用）；"
        "False=知识库未收录该地/主题，由模型基于通用知识作答（无引用）。",
    )
