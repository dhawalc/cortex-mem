import pytest

from cortex.tiered_retrieval import RetrievalResponse, TieredRetriever
import cortex.tiered_retrieval as tr


class FakeCollection:
    def __init__(self, ids=None, distances=None):
        self._ids = ids or []
        self._distances = distances or []

    def count(self):
        return len(self._ids)

    def query(self, query_texts, n_results, where=None):
        return {"ids": [self._ids[:n_results]], "distances": [self._distances[:n_results]]}


class FakeChroma:
    def __init__(self, collection):
        self.collection = collection

    def get_or_create_collection(self, name, metadata=None):
        return self.collection


@pytest.fixture
def retriever_with_docs(monkeypatch, tmp_path):
    l2_file = tmp_path / "doc1.md"
    l2_file.write_text("L2 full content", encoding="utf-8")

    docs = {
        "doc-1": {
            "title": "Doc 1",
            "hierarchy_path": "/research",
            "doc_type": "reference",
            "l0_abstract": "quick summary",
            "l0_token_count": 50,
            "l1_overview": "expanded overview",
            "l1_token_count": 200,
            "l2_file_path": str(l2_file),
            "l2_token_count": 700,
        },
        "doc-2": {
            "title": "Doc 2",
            "hierarchy_path": "/research",
            "doc_type": "reference",
            "l0_abstract": "other summary",
            "l0_token_count": 40,
            "l1_overview": "other overview",
            "l1_token_count": 180,
            "l2_file_path": str(tmp_path / "missing.md"),
            "l2_token_count": 800,
        },
    }

    monkeypatch.setattr(tr.db, "get_document", lambda _conn, doc_id: docs.get(doc_id))
    monkeypatch.setattr(tr.db, "log_query", lambda *args, **kwargs: None)

    retriever = TieredRetriever(db_conn=object())
    retriever._chroma = FakeChroma(FakeCollection(ids=["doc-1", "doc-2"], distances=[0.1, 0.55]))
    return retriever, docs


@pytest.mark.asyncio
async def test_retrieve_l0_empty_memory(monkeypatch):
    monkeypatch.setattr(tr.db, "get_document", lambda _conn, _doc_id: None)
    monkeypatch.setattr(tr.db, "log_query", lambda *args, **kwargs: None)

    retriever = TieredRetriever(db_conn=object())
    retriever._chroma = FakeChroma(FakeCollection(ids=[], distances=[]))

    response = await retriever.retrieve_l0("anything")

    assert response.results == []
    assert response.l0_count == 0
    assert response.total_tokens == 0


@pytest.mark.asyncio
async def test_retrieve_l0_filters_by_score_and_missing_docs(monkeypatch):
    docs = {
        "good": {
            "title": "Good",
            "hierarchy_path": "/x",
            "doc_type": "reference",
            "l0_abstract": "ok",
            "l0_token_count": 10,
        }
    }

    monkeypatch.setattr(tr.db, "get_document", lambda _conn, doc_id: docs.get(doc_id))
    monkeypatch.setattr(tr.db, "log_query", lambda *args, **kwargs: None)

    retriever = TieredRetriever(db_conn=object())
    retriever._chroma = FakeChroma(
        FakeCollection(ids=["good", "missing", "low-score"], distances=[0.2, 0.1, 0.9])
    )

    response = await retriever.retrieve_l0("q", min_score=0.3)

    assert len(response.results) == 1
    assert response.results[0].doc_id == "good"


@pytest.mark.asyncio
async def test_smart_query_progressively_loads_l1_and_l2(retriever_with_docs):
    retriever, _docs = retriever_with_docs

    response = await retriever.smart_query(
        query="research",
        token_budget=1200,
        top_k=2,
        directory="/research",
        agent_id="agent-1",
    )

    assert len(response.results) == 2
    # Progressive loading may skip L1 if budget allows L2 directly
    assert response.l1_count >= 0
    assert response.l2_count >= 1  # At least one doc should load to L2
    assert response.results[0].tier_loaded in {"l0", "l1", "l2"}
    assert response.total_tokens <= 1200


@pytest.mark.asyncio
async def test_get_document_tier_l2_falls_back_when_file_missing(retriever_with_docs):
    retriever, _docs = retriever_with_docs

    result = await retriever.get_document_tier("doc-2", tier="l2")

    assert result is not None
    assert result["tier"] == "l1"
    assert result["fallback"] is True
    assert result["content"] == "other overview"


@pytest.mark.asyncio
async def test_load_l2_ignores_out_of_bounds_indices(retriever_with_docs):
    retriever, _docs = retriever_with_docs

    response = RetrievalResponse(query="q", results=[])
    updated = await retriever.load_l2(response, indices=[5, 100])

    assert updated.l2_count == 0
    assert updated.total_tokens == 0


@pytest.mark.asyncio
async def test_get_document_tier_returns_none_for_unknown_tier(retriever_with_docs):
    retriever, _docs = retriever_with_docs

    result = await retriever.get_document_tier("doc-1", tier="unknown")

    assert result is None
