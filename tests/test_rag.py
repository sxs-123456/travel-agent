"""RAG 模块单元测试。

embedding / 向量库 / LLM 均用桩替换，覆盖切块、检索、prompt 组装与问答链路，
不依赖 sentence-transformers / chromadb 等重依赖。
"""
from backend.rag.chunking import split_text


def test_split_text_empty_and_short():
    assert split_text("") == []
    assert split_text("北京烤鸭好吃") == ["北京烤鸭好吃"]


def test_split_text_long_no_empty_chunks():
    sentences = [f"这是第{i}句话，用来测试切块功能是否正常。" for i in range(60)]
    text = "。".join(sentences) + "。"
    chunks = split_text(text, chunk_size=80, overlap=20)
    assert len(chunks) > 1
    assert all(c.strip() for c in chunks)


def test_split_text_overlap_between_neighbors():
    # 长文本切块后，相邻块应有重叠内容（后一块开头来自前一块结尾）
    sentences = [f"内容{i}占位文字用于填充长度。" for i in range(80)]
    text = "".join(sentences)
    chunks = split_text(text, chunk_size=60, overlap=15)
    assert len(chunks) > 1
    # 后一块的非空前缀应在前一块中出现（即存在重叠）
    assert chunks[1][:15] in chunks[0]


def test_format_context_numbers_and_sources():
    from backend.rag.query import _format_context

    chunks = [
        {"text": "故宫旺季门票60元", "source": "北京旅行攻略.md"},
        {"text": "八达岭长城门票40元", "source": "北京旅行攻略.md"},
    ]
    ctx = _format_context(chunks)
    assert "[1]" in ctx and "[2]" in ctx
    assert "北京旅行攻略.md" in ctx
    assert "故宫旺季门票60元" in ctx


def test_retrieve_returns_formatted_chunks(monkeypatch):
    import backend.rag.query as q

    monkeypatch.setattr(q, "embed_texts", lambda texts: [[0.1, 0.2]])
    monkeypatch.setattr(q, "search", lambda vec, top_k: {
        "documents": [["故宫旺季门票60元", "八达岭长城门票40元"]],
        "metadatas": [[{"source": "北京旅行攻略.md"}, {"source": "北京旅行攻略.md"}]],
        "distances": [[0.1, 0.3]],
    })
    chunks = q.retrieve("故宫门票多少钱", top_k=2)
    assert len(chunks) == 2
    assert chunks[0]["source"] == "北京旅行攻略.md"
    assert chunks[0]["score"] == 0.9   # 1 - 0.1
    assert chunks[1]["score"] == 0.7   # 1 - 0.3


def test_retrieve_filters_by_city(monkeypatch):
    """city_filter 提供时只返回该城市的 chunks，避免「问南昌却返回南宁攻略」串台
    （南昌/南宁都带"南"字，向量相似度天然偏高）。"""
    import backend.rag.query as q

    monkeypatch.setattr(q, "embed_texts", lambda texts: [[0.1, 0.2]])
    # 模拟向量库多城市：南昌 3 条 + 南宁 2 条
    monkeypatch.setattr(q, "search", lambda vec, top_k: {
        "documents": [
            ["南昌滕王阁", "南昌八一起义纪念馆", "南昌八一广场", "南宁青秀山", "南宁大明山"],
        ],
        "metadatas": [[
            {"source": "南昌旅行攻略.md"},
            {"source": "南昌旅行攻略.md"},
            {"source": "南昌旅行攻略.md"},
            {"source": "南宁旅行攻略.md"},
            {"source": "南宁旅行攻略.md"},
        ]],
        "distances": [[0.1, 0.2, 0.3, 0.35, 0.4]],
    })
    chunks = q.retrieve("南昌有什么好玩的", top_k=2, city_filter="南昌")
    assert len(chunks) == 2
    assert all("南昌" in c["source"] for c in chunks)
    assert not any("南宁" in c["source"] for c in chunks)


def test_query_knowledge_answer_with_sources(monkeypatch):
    import backend.rag.query as q
    from backend.models.rag import RagQueryResponse

    # lambda 签名加 city_filter=None 以适配新 retrieve 签名
    monkeypatch.setattr(q, "retrieve", lambda question, top_k, city_filter=None: [
        {"text": "故宫旺季门票60元", "source": "北京旅行攻略.md", "score": 0.9},
    ])

    class FakeMsg:
        content = "故宫旺季门票 60 元。"

    class FakeLLM:
        def invoke(self, prompt):
            assert "故宫旺季门票60元" in prompt  # 检索片段必须进入 prompt
            assert "北京旅行攻略.md" in prompt
            return FakeMsg()

    monkeypatch.setattr(q, "get_llm", lambda **kw: FakeLLM())
    resp = q.query_knowledge("故宫门票多少钱", top_k=1)

    assert isinstance(resp, RagQueryResponse)
    assert resp.answer == "故宫旺季门票 60 元。"
    assert resp.sources[0].source == "北京旅行攻略.md"
    assert resp.sources[0].score == 0.9


def test_query_knowledge_filters_other_cities(monkeypatch):
    """问南昌时，引用来源不应包含其他城市（如南宁）。"""
    import backend.rag.query as q
    from backend.models.rag import RagQueryResponse

    # 模拟 retrieve 用 detect_city 结果过滤后只返回南昌 chunks
    def fake_retrieve(question, top_k, city_filter=None):
        if city_filter == "南昌":
            return [{"text": "南昌滕王阁", "source": "南昌旅行攻略.md", "score": 0.9}]
        return []

    monkeypatch.setattr(q, "retrieve", fake_retrieve)

    class FakeMsg:
        content = "南昌好玩的有滕王阁。"

    class FakeLLM:
        def invoke(self, prompt):
            return FakeMsg()

    monkeypatch.setattr(q, "get_llm", lambda **kw: FakeLLM())
    resp = q.query_knowledge("南昌有什么好玩的", top_k=4)
    assert isinstance(resp, RagQueryResponse)
    assert all("南昌" in s.source for s in resp.sources)
    assert not any("南宁" in s.source for s in resp.sources)


def test_query_knowledge_empty_kb_raises(monkeypatch):
    import backend.rag.query as q
    from backend.rag.embedding import RagUnavailableError

    monkeypatch.setattr(q, "retrieve", lambda question, top_k, city_filter=None: [])
    try:
        q.query_knowledge("问题", top_k=4)
        assert False, "知识库为空应抛 RagUnavailableError"
    except RagUnavailableError:
        pass
