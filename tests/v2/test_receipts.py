from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallRequest,
    Scope,
    ScopeContext,
)
from aoms.embeddings import NullProvider
from aoms.receipts import ENGINE_VERSION, RecallReceipt
from aoms.repositories import SQLiteMemoryRepository
from aoms.repositories.sqlite import LATEST_SCHEMA_VERSION

CONTEXT = ScopeContext(agent_id="test-agent", workspace_id="test-workspace")


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
            scope_workspace_id=CONTEXT.workspace_id,
            created_by_agent_id=CONTEXT.agent_id,
            provenance=Provenance(source="receipt-fixture"),
            created_at=now,
            updated_at=now,
        )
    )
    app = AOMSApplication(
        repository, scope_context=CONTEXT, embedding_provider=NullProvider()
    )

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
async def test_read_only_fixture_recall_uses_separate_receipt_store(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.sqlite3"
    writable_source = SQLiteMemoryRepository(source_path)
    now = datetime.now(timezone.utc)
    await writable_source.store(
        MemoryRecord(
            id="fixture-decay-fact",
            kind=MemoryKind.FACT,
            content="AOMS decay bug fixture",
            scope=Scope.WORKSPACE,
            scope_workspace_id=CONTEXT.workspace_id,
            created_by_agent_id=CONTEXT.agent_id,
            provenance=Provenance(source="fixture"),
            created_at=now,
            updated_at=now,
        )
    )
    # Fold the write's WAL into the main file first. The repository opens a
    # connection per call and `with sqlite3.connect(...)` manages the
    # transaction rather than closing it, so without this the writable
    # connection checkpoints whenever it happens to be collected — and the
    # size this test compares would be recording GC timing, not whether the
    # read-only recall wrote anything.
    with sqlite3.connect(source_path) as checkpoint:
        checkpoint.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    checkpoint.close()

    before = (source_path.stat().st_size, source_path.stat().st_mtime_ns)
    source = SQLiteMemoryRepository(source_path, read_only=True)
    receipts = SQLiteMemoryRepository(tmp_path / "receipts.sqlite3")
    app = AOMSApplication(
        source,
        scope_context=CONTEXT,
        receipt_repository=receipts,
        embedding_provider=NullProvider(),
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
    assert (source_path.stat().st_size, source_path.stat().st_mtime_ns) == before


def _sized_receipt(index: int, context_bytes: int) -> RecallReceipt:
    """A receipt whose stored size is dominated by its packed context."""

    moment = datetime(2026, 8, 25, 12, index // 60, index % 60, tzinfo=timezone.utc)
    return RecallReceipt(
        receipt_id=f"sized-{index:04d}",
        created_at=moment,
        query=f"sized query {index}",
        scopes=None,
        kinds=None,
        token_budget=100_000,
        total_tokens=context_bytes // 4,
        candidate_count=0,
        top_candidates=[],
        rejected_sample=[],
        selected=[],
        latency_ms=1.0,
        engine_version=ENGINE_VERSION,
        context="c" * context_bytes,
    )


async def _saved_receipt_bytes(repository: SQLiteMemoryRepository) -> tuple[int, int]:
    receipts = await repository.recent_recall_receipts(limit=1_000)
    return len(receipts), sum(len(r.model_dump_json()) for r in receipts)


@pytest.mark.asyncio
async def test_receipt_retention_bounds_bytes_not_only_count(tmp_path: Path) -> None:
    """The count cap stopped bounding space once receipts kept the context.

    Measured on the live store, a receipt costs ~3.6 bytes per packed token on
    top of ~16KB of ranking evidence. That puts the default 1,000-receipt cap
    at 31MB for a 4,000-token budget but 377MB at the contract's 100,000-token
    ceiling, so the count alone no longer says how large the log can get.
    """

    budget = 256 * 1024
    repository = SQLiteMemoryRepository(
        tmp_path / "bytes.sqlite3",
        receipt_retention=1_000,
        receipt_byte_budget=budget,
    )
    await repository.initialize()

    for index in range(40):
        await repository.save_recall_receipt(_sized_receipt(index, 32 * 1024))

    count, total_bytes = await _saved_receipt_bytes(repository)
    assert total_bytes <= budget
    # The count cap alone would have kept all forty, about 1.3MB of context.
    assert count < 40
    assert count >= 4

    # Retention keeps the newest, so the audit trail follows the recent past.
    receipts = await repository.recent_recall_receipts(limit=1_000)
    assert receipts[0].receipt_id == "sized-0039"
    kept = {receipt.receipt_id for receipt in receipts}
    assert kept == {
        f"sized-{index:04d}" for index in range(40 - count, 40)
    }


@pytest.mark.asyncio
async def test_receipt_retention_drops_whole_receipts_and_never_truncates(
    tmp_path: Path,
) -> None:
    """Bounding the log must not cost the property that makes it worth keeping.

    A receipt earns its place by accounting for exactly what was packed. A
    truncated context would still read like that account without being one, so
    retention only ever drops receipts whole.
    """

    repository = SQLiteMemoryRepository(
        tmp_path / "whole.sqlite3",
        receipt_retention=1_000,
        receipt_byte_budget=128 * 1024,
    )
    await repository.initialize()

    written = [_sized_receipt(index, 24 * 1024) for index in range(20)]
    for receipt in written:
        await repository.save_recall_receipt(receipt)

    survivors = await repository.recent_recall_receipts(limit=1_000)
    assert survivors
    by_id = {receipt.receipt_id: receipt for receipt in written}
    for survivor in survivors:
        # Byte-for-byte the receipt that was written, context included.
        assert survivor == by_id[survivor.receipt_id]
        assert len(survivor.context or "") == 24 * 1024


@pytest.mark.asyncio
async def test_newest_receipt_survives_even_when_it_alone_exceeds_the_budget(
    tmp_path: Path,
) -> None:
    """One outsized recall must not leave the store with no audit trail."""

    repository = SQLiteMemoryRepository(
        tmp_path / "oversize.sqlite3",
        receipt_retention=1_000,
        receipt_byte_budget=16 * 1024,
    )
    await repository.initialize()

    await repository.save_recall_receipt(_sized_receipt(0, 8 * 1024))
    await repository.save_recall_receipt(_sized_receipt(1, 512 * 1024))

    receipts = await repository.recent_recall_receipts(limit=10)
    assert [receipt.receipt_id for receipt in receipts] == ["sized-0001"]
    assert len(receipts[0].context or "") == 512 * 1024


@pytest.mark.asyncio
async def test_prune_reports_both_bounds(tmp_path: Path) -> None:
    """`sweep` should say how much space the log occupies, not just how many."""

    budget = 200 * 1024
    repository = SQLiteMemoryRepository(
        tmp_path / "prune.sqlite3",
        receipt_retention=1_000,
        receipt_byte_budget=budget,
    )
    await repository.initialize()
    for index in range(30):
        await repository.save_recall_receipt(_sized_receipt(index, 20 * 1024))

    report = await repository.prune_recall_receipts(retain=1_000)

    assert report.byte_budget == budget
    assert report.remaining_bytes <= budget
    assert report.remaining_count == len(
        await repository.recent_recall_receipts(limit=1_000)
    )


@pytest.mark.asyncio
async def test_migration_backfills_sizes_for_receipts_written_before_it(
    tmp_path: Path,
) -> None:
    """An existing log must be measurable without re-reading every context.

    Retention runs inline on every save, so it reads the recorded size rather
    than the stored JSON: summing `LENGTH(receipt_json)` there cost 18.0ms per
    save against a 1,000-receipt log, where the count-only prune cost 2.2ms and
    the recorded size costs 3.0ms. Receipts written before the column existed
    have to be measured once, by the migration.
    """

    db_path = tmp_path / "backfill.sqlite3"
    repository = SQLiteMemoryRepository(db_path)
    await repository.initialize()
    written = [_sized_receipt(index, 4 * 1024) for index in range(5)]
    for receipt in written:
        await repository.save_recall_receipt(receipt)

    # Return the store to the state migration 9 has to upgrade.
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE recall_receipts SET receipt_bytes = 0")
        connection.execute("DELETE FROM schema_version WHERE version = 9")
        connection.commit()

    reopened = SQLiteMemoryRepository(db_path)
    await reopened.initialize()

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT receipt_bytes, LENGTH(CAST(receipt_json AS BLOB)) "
            "FROM recall_receipts"
        ).fetchall()
    assert rows
    assert all(recorded == actual for recorded, actual in rows)
    assert await reopened.schema_version() == LATEST_SCHEMA_VERSION
