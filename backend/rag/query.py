"""RAG 问答：向量检索 + 组装 prompt + LLM 生成带引用的答案。

完整链路：
  query → embed → 余弦检索 top-k → 相关性判定 →
    命中知识库：组装 prompt（附片段与来源）→ LLM 基于资料生成 → 答案+引用
    未命中（知识库未收录该地/主题）：LLM 基于通用知识作答 → 诚实标注「通用知识」

关键改进（解决「问到知识库没收录的城市直接报错/答非所问」）：
- 相关性判定：若用户点名了知识库已收录城市 → 走 RAG；
  若点名了真实城市但 KB 未收录（如安顺）→ 不把毫不相干的北京/西安片段喂给模型，
  而是改用通用知识兜底，并明确标注 from_kb=False；
  若未点名城市且相似度过低 → 同样走兜底，避免幻觉。
- LLM 调用统一异常兜底：任何生成失败都返回 200 友好答案，绝不向外抛 500。
"""
from __future__ import annotations

from backend.agents.base import get_llm
from backend.rag.cities import detect_city
from backend.rag.embedding import RagUnavailableError, embed_texts
from backend.rag.store import search
from backend.models.rag import RagQueryResponse, RagSource

# 通用问题（未点名任何城市）时，相似度低于此值视为知识库未覆盖，走兜底。
_SCORE_FLOOR = 0.5

_RAG_PROMPT = """你是一个旅行知识助手。请严格依据下方【参考资料】回答问题，不得编造资料中没有的信息。

【参考资料】
{context}

【问题】
{question}

要求：
1. 回答准确、简洁，优先引用参考资料中的内容；
2. 若资料中确实没有相关信息，请直接回答「知识库中未找到相关内容」，不要编造。
"""

_FALLBACK_PROMPT = """你是一个专业旅行助手。请基于你自身的通用旅行知识回答用户的问题，力求简洁、实用、准确。

{scope_hint}【用户问题】
{question}

要求：
1. 直接给出有用、可操作的回答；涉及门票、天气、交通、开放时间等可能变动的信息时，
   提醒用户出行前以官方最新公布为准；
2. 不要编造具体的文档来源或引用编号（你此刻没有参考资料）；
3. 若确实完全无法回答，坦诚说明即可。
"""


def _format_context(chunks: list[dict]) -> str:
    """把检索到的片段拼成带编号的上下文块。"""
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[{i}]（来源：{c['source']}）{c['text']}")
    return "\n\n".join(parts)


def retrieve(question: str, top_k: int = 4, city_filter: str | None = None) -> list[dict]:
    """向量检索：返回 top_k 个片段 [{text, source, score}]。

    city_filter 提供时（如用户点名的 KB 城市），只返回 metadata.source
    包含该城市名的片段——避免「问南昌却返回南宁攻略」之类的串台
    （南昌/南宁都带"南"字，余弦相似度天然偏高）。
    多取一些再过滤，保证过滤后仍有 top_k 条。
    """
    over_fetch = top_k * 4 if city_filter else top_k
    qvec = embed_texts([question])[0]
    res = search(qvec, top_k=over_fetch)
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    chunks = []
    for text, meta, dist in zip(docs, metas, dists):
        source = (meta or {}).get("source", "")
        if city_filter and city_filter not in source:
            continue
        chunks.append({
            "text": text,
            "source": source or "未知",
            "score": round(1 - float(dist), 4) if dist is not None else None,
        })
        if len(chunks) >= top_k:
            break
    return chunks


def _relevant(city: str | None, in_kb: bool, chunks: list[dict]) -> tuple[bool, str | None]:
    """判定是否应基于知识库作答。

    Args:
        city: detect_city 识别出的城市（None 表示未点名城市）
        in_kb: 该城市是否在知识库中
        chunks: 检索结果（仅 city=None 时用于相似度兜底）

    Returns:
        (relevant, unknown_city)
        - relevant: True=走 RAG；False=走通用知识兜底
        - unknown_city: 若用户点名了 KB 未收录的真实城市，返回该城市名（否则 None）
    """
    if city is not None:
        return in_kb, (None if in_kb else city)
    # 未点名城市：靠相似度兜底
    best = max((c["score"] or 0) for c in chunks) if chunks else 0
    return best >= _SCORE_FLOOR, None


def _safe_llm_answer(prompt: str) -> str | None:
    """调用 LLM 生成答案；任何异常返回 None（由上层兜底），不向外抛。"""
    try:
        llm = get_llm(temperature=0)
        return str(llm.invoke(prompt).content).strip()
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger("trip-planner").warning("RAG LLM 生成失败：%s", exc)
        return None


def query_knowledge(question: str, top_k: int = 4) -> RagQueryResponse:
    """RAG 问答入口：检索 → 相关性判定 → 生成 → 返回答案与引用来源。

    - 知识库为空（未入库/依赖缺失）抛出 RagUnavailableError（上层转 503）；
    - 命中知识库：返回 from_kb=True 与引用来源；
    - 未命中（KB 未收录该地/主题）：返回 from_kb=False 的通用知识答案，绝不报错。
    """
    # 一次性识别城市，避免重复 detect_city；KB 城市用于过滤相似但无关的其它攻略。
    city, in_kb = detect_city(question)
    city_filter = city if in_kb else None
    chunks = retrieve(question, top_k=top_k, city_filter=city_filter)
    if not chunks:
        raise RagUnavailableError(
            "知识库为空，请先入库文档（python -m backend.rag.ingest）。"
        )

    relevant, unknown_city = _relevant(city, in_kb, chunks)

    if relevant:
        context = _format_context(chunks)
        prompt = _RAG_PROMPT.format(context=context, question=question)
        answer = _safe_llm_answer(prompt)
        if answer is None:
            # LLM 失败也要优雅返回，而不是 500
            return RagQueryResponse(
                answer="抱歉，当前问答服务暂时不可用，请稍后重试。",
                sources=[],
                from_kb=True,
            )
        sources = [RagSource(source=c["source"], snippet=c["text"][:120], score=c["score"])
                   for c in chunks]
        return RagQueryResponse(answer=answer, sources=sources, from_kb=True)

    # ===== 兜底：知识库未收录，走通用知识 =====
    scope_hint = ""
    if unknown_city:
        scope_hint = (
            f"注意：本地知识库尚未收录「{unknown_city}」的专属攻略，"
            f"以下请基于通用旅行知识作答。\n"
        )
    prompt = _FALLBACK_PROMPT.format(scope_hint=scope_hint, question=question)
    answer = _safe_llm_answer(prompt)
    if answer is None:
        return RagQueryResponse(
            answer=(
                "抱歉，知识库中暂未收录该目的地/主题的专属攻略，且当前问答服务暂时不可用。"
                "你可以换种问法，或直接用「行程规划」功能生成完整方案。"
            ),
            sources=[],
            from_kb=False,
        )
    return RagQueryResponse(answer=answer, sources=[], from_kb=False)
