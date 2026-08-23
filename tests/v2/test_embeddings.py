from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aoms.application import AOMSApplication
from aoms.backfill import backfill_embeddings
from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallRequest,
    RememberRequest,
    Scope,
)
from aoms.embeddings import (
    EmbeddingProfile,
    EmbeddingProvider,
    EmbeddingVector,
    FastEmbedProvider,
    NullProvider,
    OllamaProvider,
    provider_from_config,
)
from aoms.recall import RecallRanker
from aoms.repositories import RecallCandidate, SQLiteMemoryRepository

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


class FixtureProvider:
    profile = EmbeddingProfile("fixture", "semantic-3", 3)

    def __init__(self, *, block: asyncio.Event | None = None):
        self.block = block
        self.calls = 0

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> list[EmbeddingVector | None]:
        self.calls += 1
        if self.block is not None:
            await self.block.wait()
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> EmbeddingVector | None:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> EmbeddingVector:
        folded = text.casefold()
        if any(token in folded for token in ("cat", "feline", "companion")):
            return [1.0, 0.0, 0.0]
        if any(token in folded for token in ("deploy", "release", "orchid")):
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def record(record_id: str, content: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        kind=MemoryKind.FACT,
        content=content,
        scope=Scope.WORKSPACE,
        provenance=Provenance(source="embedding-fixture"),
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_null_provider_satisfies_protocol_without_network() -> None:
    provider = NullProvider()

    assert isinstance(provider, EmbeddingProvider)
    assert provider.profile is None
    assert await provider.embed_documents(["one", "two"]) == [None, None]
    assert await provider.embed_query("query") is None


def test_provider_selection_is_configuration_driven_without_loading_models() -> None:
    default = provider_from_config({})
    ollama = provider_from_config(
        {
            "AOMS_EMBEDDING_PROVIDER": "ollama",
            "AOMS_OLLAMA_URL": "http://fixture.invalid:11434",
        }
    )

    assert isinstance(default, FastEmbedProvider)
    assert default.profile.dimensions == 384
    assert isinstance(ollama, OllamaProvider)
    assert ollama.profile.model == "nomic-embed-text"
    assert ollama.profile.dimensions == 768


@pytest.mark.asyncio
async def test_vector_upsert_and_cosine_knn_round_trip(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "vectors.sqlite3")
    profile = FixtureProvider.profile
    feline = record("feline", "A feline rests on the sofa")
    release = record("release", "Deploy the orchid release")
    await repository.store_many([feline, release])

    await repository.upsert_vector(feline, profile, [1.0, 0.0, 0.0])
    await repository.upsert_vector(release, profile, [0.0, 1.0, 0.0])
    hits = await repository.vector_knn([0.9, 0.1, 0.0], profile, limit=2)

    assert [hit.memory_id for hit in hits] == ["feline", "release"]
    assert hits[0].score > hits[1].score
    await repository.upsert_vector(feline, profile, [0.0, 0.0, 1.0])
    updated = await repository.vector_knn([0.0, 0.0, 1.0], profile, limit=1)
    assert updated[0].memory_id == "feline"


@pytest.mark.asyncio
async def test_remember_queues_durably_and_does_not_wait_for_provider(
    tmp_path: Path,
) -> None:
    gate = asyncio.Event()
    provider = FixtureProvider(block=gate)
    repository = SQLiteMemoryRepository(tmp_path / "pending.sqlite3")
    app = AOMSApplication(repository, embedding_provider=provider)

    remembered = await asyncio.wait_for(
        app.remember(
            RememberRequest(
                id="queued",
                kind=MemoryKind.FACT,
                content="A feline companion",
            )
        ),
        timeout=1,
    )

    assert remembered.record.id == "queued"
    assert await repository.pending_embedding_count(provider.profile) == 1
    gate.set()
    await app.wait_for_background_embeddings()
    assert await repository.pending_embedding_count(provider.profile) == 0
    assert (await repository.vector_knn([1.0, 0.0, 0.0], provider.profile, limit=1))[
        0
    ].memory_id == "queued"


@pytest.mark.asyncio
async def test_backfill_is_idempotent_and_resumes_after_batch_limit(
    tmp_path: Path,
) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "backfill.sqlite3")
    provider = FixtureProvider()
    await repository.store_many(
        [
            record("a", "A feline companion"),
            record("b", "Deploy the orchid release"),
            record("c", "An unrelated note"),
        ]
    )

    interrupted = await backfill_embeddings(
        repository, provider, batch_size=1, max_batches=1
    )
    resumed = await backfill_embeddings(repository, provider, batch_size=1)
    repeated = await backfill_embeddings(repository, provider, batch_size=2)

    assert interrupted.embedded == 1
    assert resumed.embedded == 2
    assert resumed.pending == 0
    assert repeated.queued == 0
    assert repeated.embedded == 0
    assert await repository.pending_embedding_count(provider.profile) == 0


@pytest.mark.asyncio
async def test_vector_recall_and_graceful_zero_coverage_receipts(
    tmp_path: Path,
) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "recall.sqlite3")
    provider = FixtureProvider()
    feline = record("semantic", "A feline sleeps beside its person")
    other = record("other", "Database maintenance notes")
    await repository.store_many([feline, other])
    await repository.upsert_vector(feline, provider.profile, [1.0, 0.0, 0.0])

    semantic_app = AOMSApplication(repository, embedding_provider=provider)
    semantic = await semantic_app.recall(
        RecallRequest(task="companion animal", token_budget=1_000)
    )

    assert semantic.sources[0].memory_id == "semantic"
    assert semantic.diagnostics["vector_coverage"] > 0.0
    receipt = (await semantic_app.recent_recall_receipts(limit=1))[0]
    vector_candidate = next(
        item for item in receipt.top_candidates if item.memory_id == "semantic"
    )
    assert vector_candidate.breakdown["vector"].weight == pytest.approx(0.35)
    assert vector_candidate.breakdown["vector"].raw == pytest.approx(1.0)
    assert receipt.vector_coverage == semantic.diagnostics["vector_coverage"]

    lexical_repository = SQLiteMemoryRepository(tmp_path / "lexical.sqlite3")
    await lexical_repository.store(record("lexical", "Orchid deployment runbook"))
    lexical_app = AOMSApplication(lexical_repository, embedding_provider=NullProvider())
    lexical = await lexical_app.recall(
        RecallRequest(task="orchid deployment", token_budget=1_000)
    )
    lexical_receipt = (await lexical_app.recent_recall_receipts(limit=1))[0]

    assert lexical.sources[0].memory_id == "lexical"
    assert lexical.diagnostics["vector_coverage"] == 0.0
    breakdown = lexical_receipt.top_candidates[0].breakdown
    assert breakdown["vector"].weight == 0.0
    assert sum(component.weight for component in breakdown.values()) == pytest.approx(
        1.0
    )


def test_partial_vector_coverage_renormalizes_only_missing_candidate() -> None:
    request = RecallRequest(task="companion")
    candidates = [
        RecallCandidate(record("with", "feline"), 0.0, ("vector",), 0.9),
        RecallCandidate(record("without", "note"), 0.0, ("recent-kind",), None),
    ]

    ranked = RecallRanker().rank(candidates, request, now=NOW)
    by_id = {item.candidate.record.id: item for item in ranked}

    assert by_id["with"].breakdown["vector"].weight == pytest.approx(0.35)
    assert by_id["without"].breakdown["vector"].weight == 0.0
    assert by_id["without"].breakdown["fts"].weight == pytest.approx(0.40 / 0.65)
    assert sum(
        component.weight for component in by_id["without"].breakdown.values()
    ) == pytest.approx(1.0)
