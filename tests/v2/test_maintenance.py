from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aoms.application import AOMSApplication
from aoms.contracts import MemoryKind, RecallRequest, RememberRequest, ScopeContext
from aoms.embeddings import EmbeddingProfile, EmbeddingVector, NullProvider
from aoms.repositories import SQLiteMemoryRepository

CONTEXT = ScopeContext(agent_id="maintenance-agent", workspace_id="maintenance-workspace")


class FixtureProvider:
    profile = EmbeddingProfile("fixture", "maintenance", 3)

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> list[EmbeddingVector | None]:
        return [[1.0, 0.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> EmbeddingVector | None:
        return [1.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_embedding_catch_up_reclaims_and_drains_an_expired_lease(
    tmp_path: Path,
) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "embeddings.sqlite3")
    provider = FixtureProvider()
    app = AOMSApplication(
        repository,
        scope_context=CONTEXT,
        embedding_provider=provider,
        background_embeddings=False,
    )
    await app.remember(
        RememberRequest(
            id="expired-lease",
            kind=MemoryKind.FACT,
            content="embedding lease fixture",
        )
    )
    leased = await repository.claim_pending_embeddings(
        provider.profile, limit=1, lease_seconds=300
    )
    assert len(leased) == 1
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "UPDATE embedding_pending SET claimed_at = ? WHERE record_id = ?",
            (expired_at.isoformat(), "expired-lease"),
        )
        connection.commit()

    report = await app.catch_up_embeddings(lease_seconds=60)

    assert report.claimed == 1
    assert report.embedded == 1
    assert report.failed == 0
    assert await repository.pending_embedding_count(provider.profile) == 0


@pytest.mark.asyncio
async def test_receipt_retention_prune_returns_typed_counts(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(
        tmp_path / "receipts.sqlite3", receipt_retention=100
    )
    app = AOMSApplication(
        repository,
        scope_context=CONTEXT,
        embedding_provider=NullProvider(),
    )
    for query in ("first fixture", "second fixture", "third fixture"):
        await app.recall(RecallRequest(task=query))

    report = await app.prune_recall_receipts(retain=2)

    assert report.retained_limit == 2
    assert report.deleted_count == 1
    assert report.remaining_count == 2
    assert len(await app.recent_recall_receipts(limit=10)) == 2


@pytest.mark.asyncio
async def test_integrity_report_compares_counts_and_detects_orphans(
    tmp_path: Path,
) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "integrity.sqlite3")
    provider = FixtureProvider()
    app = AOMSApplication(
        repository,
        scope_context=CONTEXT,
        embedding_provider=provider,
        background_embeddings=False,
    )
    for record_id in ("healthy", "will-be-orphaned"):
        await app.remember(
            RememberRequest(
                id=record_id,
                kind=MemoryKind.FACT,
                content=f"integrity fixture {record_id}",
            )
        )
    sweep = await app.catch_up_embeddings()
    assert sweep.embedded == 2

    healthy = await app.check_integrity()
    assert healthy.healthy is True
    assert healthy.memory_count == 2
    assert healthy.fts_count == 2
    assert healthy.vector_count == 2
    assert healthy.orphan_fts_memory_ids == []
    assert healthy.orphan_vector_memory_ids == []

    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "DELETE FROM memories WHERE id = ?", ("will-be-orphaned",)
        )
        connection.execute(
            "DELETE FROM memories_fts WHERE rowid = "
            "(SELECT rowid FROM memories WHERE id = ?)",
            ("healthy",),
        )
        connection.commit()

    broken = await app.check_integrity()

    assert broken.healthy is False
    assert broken.memory_count == 1
    assert broken.fts_count == 1
    assert broken.vector_count == 2
    assert broken.missing_fts_memory_ids == ["healthy"]
    assert broken.orphan_fts_memory_ids == ["will-be-orphaned"]
    assert broken.orphan_vector_memory_ids == ["will-be-orphaned"]


def _seed_projected_records(repository: SQLiteMemoryRepository, count: int) -> None:
    """Fill both the canonical table and its FTS projection, cheaply.

    The integrity scaling test needs thousands of records; going through
    ``remember`` would spend the whole budget on per-write fsyncs. These rows
    only have to be internally consistent, so one transaction of direct
    inserts is enough.
    """

    payload = '{"disposition": "admitted"}'
    rows = [
        (
            f"scale-{index:06d}",
            MemoryKind.FACT.value,
            "user_global",
            None,
            None,
            "scale-actor",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            payload,
            None,
            0,
        )
        for index in range(count)
    ]
    with sqlite3.connect(repository.db_path) as connection:
        connection.executemany(
            "INSERT INTO memories(id, kind, scope, scope_agent_id, "
            "scope_workspace_id, created_by_agent_id, created_at, updated_at, "
            "record_json, claim_key, contested) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.executemany(
            "INSERT INTO memories_fts(rowid, id, content, tags, kind) "
            "VALUES ((SELECT rowid FROM memories WHERE id = ?), ?, ?, ?, ?)",
            [
                (row[0], row[0], f"scale fixture body {index}", "", row[1])
                for index, row in enumerate(rows)
            ],
        )
        connection.commit()


async def _integrity_vm_steps(
    repository: SQLiteMemoryRepository, count: int
) -> int:
    """Run the report and return the SQLite VM steps it burned.

    Wall-clock would make this test a machine-speed measurement. Counting
    virtual-machine steps measures the shape of the work instead, so the
    assertion means the same thing on a laptop and in CI.
    """

    steps = 0
    connect = repository._connect

    def counting_connect() -> sqlite3.Connection:
        connection = connect()

        def handler() -> int:
            nonlocal steps
            steps += 1
            return 0

        connection.set_progress_handler(handler, 1000)
        return connection

    repository._connect = counting_connect  # type: ignore[method-assign]
    try:
        report = await repository.integrity_report()
    finally:
        repository._connect = connect  # type: ignore[method-assign]
    assert report.healthy is True
    assert report.memory_count == count
    assert report.missing_fts_memory_ids == []
    assert report.orphan_fts_memory_ids == []
    return steps * 1000


@pytest.mark.asyncio
async def test_integrity_report_work_stays_linear_in_store_size(
    tmp_path: Path,
) -> None:
    """Guard the report against ever re-acquiring an O(n^2) projection scan.

    The FTS ``id`` column is ``UNINDEXED``, so joining canonical rows to it by
    id makes every record drive a full scan of the projection. On the
    165,347-record store that phrasing cost ~84ms per record — just under four
    hours for the one command an operator runs when they suspect corruption.

    Quadrupling the store must not do more than about four times the work.
    Measured, the linear report spends ~15 VM steps per record; the join
    phrasing spent ~26,000 at 2,000 records and kept climbing.
    """

    small_count, large_count = 500, 2_000
    small = SQLiteMemoryRepository(tmp_path / "scale-small.sqlite3")
    await small.initialize()
    _seed_projected_records(small, small_count)
    large = SQLiteMemoryRepository(tmp_path / "scale-large.sqlite3")
    await large.initialize()
    _seed_projected_records(large, large_count)

    small_steps = await _integrity_vm_steps(small, small_count)
    large_steps = await _integrity_vm_steps(large, large_count)

    # Linear work quadruples; the quadratic join multiplied by ~16.
    assert large_steps < small_steps * 8, (
        f"integrity_report scaled super-linearly: {small_steps} steps at "
        f"{small_count} records, {large_steps} at {large_count}"
    )
    # An absolute ceiling catches a regression that inflates both sides.
    assert large_steps < large_count * 200, (
        f"integrity_report burned {large_steps} steps on {large_count} "
        "records; the linear report needs about 15 per record"
    )
