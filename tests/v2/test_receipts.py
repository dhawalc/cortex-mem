from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from aoms.application import AOMSApplication
from aoms.contracts import MemoryKind, MemoryRecord, Provenance, RecallRequest, Scope
from aoms.embeddings import NullProvider
from aoms.receipts import ENGINE_VERSION, RecallReceipt
from aoms.repositories import SQLiteMemoryRepository


@pytest.mark.asyncio
async def test_receipt_emission_retrieval_and_retention_cap(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3", receipt_retention=2)
    now = datetime.now(timezone.utc)
    await repository.store(
        MemoryRecord(
            id="orchid-fact",
            kind=MemoryKind.FACT,
            content="Orchid deployment uses a blue canary",
            scope=Scope.WORKSPACE,
            provenance=Provenance(source="receipt-fixture"),
            created_at=now,
            updated_at=now,
        )
    )
    app = AOMSApplication(repository, embedding_provider=NullProvider())

    for query in ("orchid first", "orchid second", "orchid third"):
        result = await app.recall(RecallRequest(task=query, token_budget=300))
        assert result.sources

    receipts = await app.recent_recall_receipts(limit=10)

    assert [receipt.query for receipt in receipts] == ["orchid third", "orchid second"]
    newest = receipts[0]
    assert newest.schema_version == 1
    assert newest.engine_version == ENGINE_VERSION
    assert newest.candidate_count >= 1
    assert newest.selected[0].memory_id == "orchid-fact"
    assert newest.selected[0].token_cost == newest.total_tokens
    assert newest.top_candidates[0].breakdown.keys() == {
        "fts",
        "vector",
        "recency",
        "scope_specificity",
    }
    assert newest.vector_coverage == 0.0
    assert RecallReceipt.model_validate_json(newest.model_dump_json()) == newest


@pytest.mark.asyncio
async def test_read_only_real_import_recall_uses_separate_receipt_store(
    tmp_path: Path,
) -> None:
    real_db = Path.home() / ".local" / "share" / "aoms" / "aoms.sqlite3"
    if not real_db.is_file():
        pytest.skip(f"real imported AOMS database is absent: {real_db}")

    before = (real_db.stat().st_size, real_db.stat().st_mtime_ns)
    source = SQLiteMemoryRepository(real_db, read_only=True)
    receipts = SQLiteMemoryRepository(tmp_path / "receipts.sqlite3")
    app = AOMSApplication(
        source, receipt_repository=receipts, embedding_provider=NullProvider()
    )

    result = await app.recall(
        RecallRequest(
            task="what happened with the AOMS decay bug",
            token_budget=1_000,
        )
    )
    stored = await app.recent_recall_receipts(limit=1)

    assert result.token_count <= 1_000
    assert result.token_count > 0
    assert len(result.sources) >= 1
    assert stored[0].receipt_id == result.diagnostics["receipt_id"]
    assert stored[0].total_tokens == result.token_count
    assert (real_db.stat().st_size, real_db.stat().st_mtime_ns) == before
