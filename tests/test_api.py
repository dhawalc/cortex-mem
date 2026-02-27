import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

import service.api as api


class FakeStorage:
    def __init__(self):
        self.append_calls = []
        self.search_calls = []
        self.weight_calls = []

    async def append(self, tier, entry_type, payload, tags=None, weight=None):
        record = {
            "id": f"entry-{len(self.append_calls) + 1}",
            "_tier": tier,
            "_type": entry_type,
            **payload,
            "tags": tags or [],
            "weight": weight if weight is not None else 1.0,
        }
        self.append_calls.append(record)
        return record

    async def search(self, query, tiers=None, limit=10, date_from=None, date_to=None, min_weight=None):
        self.search_calls.append(
            {
                "query": query,
                "tiers": tiers,
                "limit": limit,
                "date_from": date_from,
                "date_to": date_to,
                "min_weight": min_weight,
            }
        )
        return [{"tier": "episodic", "type": "experience", "entry": {"title": "hit"}, "score": 1.0, "line_number": 1}]

    async def adjust_weight(self, entry_id, tier, task_score):
        self.weight_calls.append({"entry_id": entry_id, "tier": tier, "task_score": task_score})
        if entry_id == "missing":
            return None
        return {"id": entry_id, "weight": 1.2}

    async def browse(self, path):
        if path == "missing/path":
            return {"path": path, "exists": False, "subdirs": [], "files": []}
        return {"path": path or "/", "exists": True, "subdirs": ["memory"], "files": ["MEMORY.md"]}

    async def count_entries(self):
        return {"episodic": 5, "semantic": 3, "procedural": 2}


class FakeRetriever:
    def __init__(self):
        self.calls = []
        self.conn = object()  # Mock DB connection for health checks

    async def smart_query(self, **kwargs):
        self.calls.append(kwargs)

        class Resp:
            def to_dict(self_inner):
                return {
                    "query": kwargs["query"],
                    "total_results": 1,
                    "total_tokens": 100,
                    "tiers": {"l0": 1, "l1": 0, "l2": 0},
                    "latency_ms": 1,
                    "results": [{"doc_id": "doc-1", "tier_loaded": "l0", "tokens_used": 100}],
                }

        return Resp()

    async def get_document_tier(self, doc_id, tier="l0"):
        if doc_id == "missing":
            return None
        return {"doc_id": doc_id, "tier": tier, "content": "ok", "tokens": 10}


class FakeGenerator:
    def __init__(self):
        self.conn = object()
        self.regenerated = []

    async def ingest_document(self, **kwargs):
        return "doc-123"

    async def regenerate(self, doc_id):
        self.regenerated.append(doc_id)
        return doc_id != "missing"


@pytest.fixture
def client(monkeypatch):
    fake_storage = FakeStorage()
    fake_retriever = FakeRetriever()
    fake_generator = FakeGenerator()

    monkeypatch.setattr(api, "storage", fake_storage)
    monkeypatch.setattr(api, "_get_retriever", lambda: fake_retriever)
    monkeypatch.setattr(api, "_get_generator", lambda: fake_generator)
    monkeypatch.setattr(
        "cortex.db.get_all_documents",
        lambda _conn: [
            {
                "doc_id": "doc-1",
                "title": "Doc",
                "hierarchy_path": "/research",
                "doc_type": "reference",
                "l0_token_count": 10,
                "l1_token_count": 20,
                "l2_token_count": 30,
                "is_stale": False,
            }
        ],
    )
    monkeypatch.setattr(
        "cortex.db.get_document",
        lambda _conn, _doc_id: {"l0_token_count": 10, "l1_token_count": 20, "l2_token_count": 30},
    )

    return TestClient(api.app), fake_storage, fake_retriever, fake_generator


def test_memory_search_rejects_invalid_tier(client):
    test_client, _storage, _retriever, _generator = client

    response = test_client.post("/memory/search", json={"query": "x", "tier": ["working"]})

    assert response.status_code == 400
    assert "Invalid tier" in response.json()["detail"]


def test_memory_write_and_search(client):
    test_client, storage, _retriever, _generator = client

    write_resp = test_client.post(
        "/memory/episodic",
        json={"type": "experience", "payload": {"title": "test", "outcome": "ok"}},
    )
    search_resp = test_client.post("/memory/search", json={"query": "test", "limit": 5})

    assert write_resp.status_code == 200
    assert write_resp.json()["status"] == "ok"
    assert search_resp.status_code == 200
    assert search_resp.json()["total"] == 1
    assert storage.search_calls[0]["query"] == "test"


def test_weight_update_not_found_returns_404(client):
    test_client, _storage, _retriever, _generator = client

    response = test_client.post(
        "/memory/weight",
        json={"entry_id": "missing", "tier": "episodic", "task_score": 0.9},
    )

    assert response.status_code == 404


def test_cortex_query_passes_token_budget_and_filters(client):
    test_client, _storage, retriever, _generator = client

    response = test_client.post(
        "/cortex/query",
        json={"query": "memory", "token_budget": 1234, "top_k": 3, "directory": "/research", "agent_id": "a1"},
    )

    assert response.status_code == 200
    assert retriever.calls[0]["token_budget"] == 1234
    assert retriever.calls[0]["top_k"] == 3
    assert retriever.calls[0]["directory"] == "/research"
    assert retriever.calls[0]["agent_id"] == "a1"


def test_cortex_document_not_found_returns_404(client):
    test_client, _storage, _retriever, _generator = client

    response = test_client.get("/cortex/document/missing?tier=l1")

    assert response.status_code == 404


def test_health_and_documents_endpoints(client):
    test_client, _storage, _retriever, _generator = client

    health = test_client.get("/health")
    docs = test_client.get("/cortex/documents")

    assert health.status_code == 200
    assert health.json()["tiers"] == {"episodic": 5, "semantic": 3, "procedural": 2}
    assert docs.status_code == 200
    assert docs.json()["total"] == 1


@pytest.mark.asyncio
async def test_concurrent_memory_writes(client):
    _test_client, storage, _retriever, _generator = client

    transport = httpx.ASGITransport(app=api.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        async def write_one(i):
            return await async_client.post(
                "/memory/episodic",
                json={"type": "experience", "payload": {"title": f"evt-{i}", "outcome": "ok"}},
            )

        responses = await asyncio.gather(*[write_one(i) for i in range(40)])

    assert all(r.status_code == 200 for r in responses)
    assert len(storage.append_calls) == 40
