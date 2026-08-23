import asyncio
import json
import threading
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import service.api as api
from service.models import MemoryWrite
from service.storage import MemoryStorage


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
    monkeypatch.setattr(api, "_schedule_embed_on_write", lambda _tier, _record: None)
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
    assert health.json()["tiers"] == {}  # /health is intentionally lightweight (e0bb673); counts come from /stats
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


@pytest.mark.asyncio
async def test_stats_scan_is_offloaded_and_cached(monkeypatch, tmp_path):
    filepath = tmp_path / "modules/memory/episodic/experiences.jsonl"
    filepath.parent.mkdir(parents=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    schema = {"schema": "experience-v1"}
    first = {"id": "one", "_type": "experience", "weight": 0.4, "ts": timestamp}
    second = {"id": "two", "_type": "decision", "weight": 2.0, "ts": timestamp}
    filepath.write_text(
        json.dumps(schema) + "\n" + json.dumps(first) + json.dumps(second),
        encoding="utf-8",
    )

    monkeypatch.setattr(api, "storage", MemoryStorage(tmp_path))
    monkeypatch.setattr(api, "_stats_cache", None)
    monkeypatch.setattr(api, "_stats_cache_expires_at", 0.0)
    monkeypatch.setattr(api, "_stats_cache_lock", asyncio.Lock())

    from service import vector_store

    async def fake_index_stats():
        return {"episodic": 2, "semantic": 0, "procedural": 0}

    monkeypatch.setattr(vector_store, "get_index_stats", fake_index_stats)
    original_scan = api._scan_memory_stats
    scan_threads = []

    def tracked_scan(storage_instance):
        scan_threads.append(threading.get_ident())
        return original_scan(storage_instance)

    monkeypatch.setattr(api, "_scan_memory_stats", tracked_scan)
    event_loop_thread = threading.get_ident()

    first_result = await api.get_stats()
    second_result = await api.get_stats()

    assert len(scan_threads) == 1
    assert scan_threads[0] != event_loop_thread
    assert first_result.total_entries == 2
    assert first_result.by_type == {"experience": 1, "decision": 1}
    assert first_result.weight_distribution == {"low": 1, "medium": 0, "high": 1}
    assert first_result.computed_at == second_result.computed_at


@pytest.mark.asyncio
async def test_memory_write_schedules_embedding_without_waiting(monkeypatch):
    from service import embeddings, vector_store

    fake_storage = FakeStorage()
    embed_started = asyncio.Event()
    release_embedding = asyncio.Event()
    indexed = asyncio.Event()
    indexed_entry = {}

    async def fake_embedding(text):
        embed_started.set()
        await release_embedding.wait()
        return [0.1, 0.2]

    async def fake_add_to_index(**kwargs):
        indexed_entry.update(kwargs)
        indexed.set()
        return True

    monkeypatch.setattr(api, "storage", fake_storage)
    monkeypatch.setattr(embeddings, "get_embedding", fake_embedding)
    monkeypatch.setattr(vector_store, "add_to_index", fake_add_to_index)

    response = await api.write_memory(
        "episodic",
        MemoryWrite(type="experience", payload={"title": "test", "outcome": "ok"}),
    )
    await asyncio.wait_for(embed_started.wait(), timeout=1)

    assert response["status"] == "ok"
    assert not indexed.is_set()

    release_embedding.set()
    await asyncio.wait_for(indexed.wait(), timeout=1)
    assert indexed_entry["entry_id"] == response["id"]
    assert indexed_entry["tier"] == "episodic"


@pytest.mark.asyncio
async def test_embed_failure_writes_unindexed_marker(monkeypatch, tmp_path):
    from service import embeddings

    marker_path = tmp_path / "unindexed_ids.jsonl"

    async def failed_embedding(_text):
        return None

    monkeypatch.setattr(api, "UNINDEXED_IDS_PATH", marker_path)
    monkeypatch.setattr(embeddings, "get_embedding", failed_embedding)

    await api._embed_and_index_record(
        "semantic",
        {
            "id": "failed-id",
            "_tier": "semantic",
            "_type": "fact",
            "content": "remember me",
            "weight": 1.0,
        },
    )

    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["id"] == "failed-id"
    assert marker["tier"] == "semantic"
    assert "no vector" in marker["error"]
