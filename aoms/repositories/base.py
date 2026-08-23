"""Repository protocol used by the transport-independent application layer."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    RecallRequest,
    Scope,
    SearchRequest,
    SearchResult,
)
from aoms.embeddings import EmbeddingProfile, EmbeddingVector
from aoms.receipts import RecallReceipt


@dataclass(frozen=True, slots=True)
class RecallCandidate:
    """Repository-neutral candidate evidence consumed by recall scorers."""

    record: MemoryRecord
    fts_score: float
    retrieval_sources: tuple[str, ...]
    vector_score: float | None = None


@dataclass(frozen=True, slots=True)
class VectorHit:
    """Repository-neutral cosine-similarity result."""

    memory_id: str
    score: float


@dataclass(frozen=True, slots=True)
class PendingEmbedding:
    """One leased durable queue item and its current canonical record."""

    record: MemoryRecord
    profile: EmbeddingProfile
    claim_token: str
    attempts: int


@dataclass(frozen=True, slots=True)
class CompletedEmbedding:
    pending: PendingEmbedding
    vector: EmbeddingVector


@runtime_checkable
class VectorRepository(Protocol):
    async def store_with_embedding_pending(
        self, record: MemoryRecord, profile: EmbeddingProfile
    ) -> MemoryRecord: ...

    async def upsert_vector(
        self,
        record: MemoryRecord,
        profile: EmbeddingProfile,
        vector: EmbeddingVector,
    ) -> None: ...

    async def vector_knn(
        self,
        vector: EmbeddingVector,
        profile: EmbeddingProfile,
        *,
        limit: int,
        kinds: Sequence[MemoryKind] | None = None,
        scopes: Sequence[Scope] | None = None,
    ) -> list[VectorHit]: ...

    async def claim_pending_embeddings(
        self,
        profile: EmbeddingProfile,
        *,
        limit: int,
        lease_seconds: int = 300,
    ) -> list[PendingEmbedding]: ...

    async def complete_pending_embeddings(
        self, completed: Sequence[CompletedEmbedding]
    ) -> int: ...

    async def fail_pending_embeddings(
        self, pending: Sequence[PendingEmbedding], error: str
    ) -> int: ...

    async def scan_records_for_embedding(
        self,
        profile: EmbeddingProfile,
        *,
        after_id: str | None,
        limit: int,
    ) -> tuple[list[MemoryRecord], str | None, int]: ...

    async def enqueue_unembedded(
        self, records: Sequence[MemoryRecord], profile: EmbeddingProfile
    ) -> int: ...

    async def pending_embedding_count(self, profile: EmbeddingProfile) -> int: ...


class MemoryRepository(Protocol):
    async def initialize(self) -> None: ...

    async def store(self, record: MemoryRecord) -> MemoryRecord: ...

    async def store_many(
        self, records: Sequence[MemoryRecord]
    ) -> list[MemoryRecord]: ...

    async def get(self, record_id: str) -> MemoryRecord | None: ...

    async def search_by_keyword(self, request: SearchRequest) -> SearchResult: ...

    async def retrieve_recall_candidates(
        self,
        request: RecallRequest,
        *,
        limit: int = 100,
        query_vector: EmbeddingVector | None = None,
        vector_profile: EmbeddingProfile | None = None,
    ) -> list[RecallCandidate]: ...

    async def save_recall_receipt(self, receipt: RecallReceipt) -> None: ...

    async def recent_recall_receipts(
        self, *, limit: int = 20
    ) -> list[RecallReceipt]: ...

    async def list(
        self,
        *,
        kinds: list[MemoryKind] | None = None,
        scopes: list[Scope] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]: ...
