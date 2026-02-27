import asyncio
import json

import pytest

from service.storage import MemoryStorage, _resolve_file


@pytest.mark.asyncio
async def test_empty_memory_returns_no_search_results(tmp_path):
    storage = MemoryStorage(tmp_path)

    results = await storage.search(query="does-not-exist")

    assert results == []


@pytest.mark.asyncio
async def test_episodic_semantic_procedural_roundtrip_search(tmp_path):
    storage = MemoryStorage(tmp_path)

    await storage.append(
        tier="episodic",
        entry_type="experience",
        payload={
            "ts": "2026-02-26T12:00:00+00:00",
            "type": "achievement",
            "title": "Shipped AOMS",
            "outcome": "Success",
        },
        tags=["release"],
    )
    await storage.append(
        tier="semantic",
        entry_type="fact",
        payload={
            "ts": "2026-02-26T12:00:00+00:00",
            "subject": "AOMS",
            "predicate": "supports",
            "object": "tiered retrieval",
        },
    )
    await storage.append(
        tier="procedural",
        entry_type="skill",
        payload={
            "ts": "2026-02-26T12:00:00+00:00",
            "skill_name": "incident_response",
            "category": "ops",
            "when_to_use": "when production is degraded",
            "success_rate": 0.8,
        },
    )

    results = await storage.search(query="AOMS retrieval degraded", limit=10)
    tiers = {r["tier"] for r in results}

    assert {"episodic", "semantic", "procedural"}.issubset(tiers)


@pytest.mark.asyncio
async def test_large_batch_write_and_count(tmp_path):
    storage = MemoryStorage(tmp_path)

    for idx in range(250):
        await storage.append(
            tier="episodic",
            entry_type="experience",
            payload={
                "ts": "2026-02-26T12:00:00+00:00",
                "type": "observation",
                "title": f"event-{idx}",
                "outcome": "ok",
            },
        )

    counts = await storage.count_entries()
    limited = await storage.search(query="event", tiers=["episodic"], limit=100)

    assert counts["episodic"] == 250
    assert len(limited) == 100


@pytest.mark.asyncio
async def test_concurrent_appends_are_all_persisted(tmp_path):
    storage = MemoryStorage(tmp_path)

    async def write_one(i: int):
        return await storage.append(
            tier="episodic",
            entry_type="experience",
            payload={
                "ts": "2026-02-26T12:00:00+00:00",
                "type": "observation",
                "title": f"concurrent-{i}",
                "outcome": "ok",
            },
        )

    written = await asyncio.gather(*[write_one(i) for i in range(75)])
    counts = await storage.count_entries()

    assert len(written) == 75
    assert counts["episodic"] == 75


@pytest.mark.asyncio
async def test_weight_adjustment_not_found_returns_none(tmp_path):
    storage = MemoryStorage(tmp_path)

    updated = await storage.adjust_weight(
        entry_id="missing-id",
        tier="episodic",
        task_score=0.9,
    )

    assert updated is None


def test_working_tier_currently_unsupported(tmp_path):
    with pytest.raises(ValueError, match="Unknown tier: working"):
        _resolve_file(tmp_path, "working", "context")


@pytest.mark.asyncio
async def test_search_skips_invalid_json_lines(tmp_path):
    storage = MemoryStorage(tmp_path)
    path = _resolve_file(tmp_path, "episodic", "experience")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "not-json\n"
        + json.dumps({"schema": "header"})
        + "\n"
        + json.dumps(
            {
                "id": "1",
                "ts": "2026-02-26T12:00:00+00:00",
                "title": "valid line",
                "weight": 1.0,
                "_tier": "episodic",
                "_type": "experience",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    results = await storage.search(query="valid")

    assert len(results) == 1
    assert results[0]["entry"]["id"] == "1"
