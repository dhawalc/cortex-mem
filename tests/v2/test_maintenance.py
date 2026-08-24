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
