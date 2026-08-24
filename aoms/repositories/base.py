"""Repository protocol used by the transport-independent application layer."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    IntegrityReport,
    RecallRequest,
    Scope,
    ScopeContext,
    SearchRequest,
    SearchResult,
    ReceiptPruneReport,
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
class RecallCandidateBatch:
    """Visible candidates plus a content-free count rejected by scope policy."""

    candidates: tuple[RecallCandidate, ...]
    scope_filtered_count: int = 0


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


@dataclass(frozen=True, slots=True)
class ConditionalStoreResult:
    """Result of an atomic model-facing insert-or-retain decision."""

    record: MemoryRecord
    created: bool


class RecordContentConflictError(ValueError):
    """A conditional store retained a different record with the same id."""

    def __init__(self, retained: MemoryRecord):
        super().__init__(f"record {retained.id!r} already has different content")
        self.retained = retained


@runtime_checkable
class VectorRepository(Protocol):
    async def store_with_embedding_pending(
        self, record: MemoryRecord, profile: EmbeddingProfile
    ) -> MemoryRecord: ...

    async def store_new_with_embedding_pending(
        self, record: MemoryRecord, profile: EmbeddingProfile
    ) -> MemoryRecord: ...

    async def store_if_content_unchanged_with_embedding_pending(
        self, record: MemoryRecord, profile: EmbeddingProfile
    ) -> ConditionalStoreResult: ...

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
        scope_context: ScopeContext | None = None,
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

    async def store_new(self, record: MemoryRecord) -> MemoryRecord: ...

    async def store_if_content_unchanged(
        self, record: MemoryRecord
    ) -> ConditionalStoreResult: ...

    async def store_many(
        self, records: Sequence[MemoryRecord]
    ) -> list[MemoryRecord]: ...

    async def get(self, record_id: str) -> MemoryRecord | None: ...

    async def visible_memory_count(
        self,
        *,
        kinds: Sequence[MemoryKind] | None = None,
        scopes: Sequence[Scope] | None = None,
        scope_context: ScopeContext | None = None,
    ) -> int: ...

    async def search_by_keyword(
        self,
        request: SearchRequest,
        *,
        scope_context: ScopeContext | None = None,
        as_of: datetime | None = None,
    ) -> SearchResult: ...

    async def retrieve_recall_candidates(
        self,
        request: RecallRequest,
        *,
        limit: int = 100,
        query_vector: EmbeddingVector | None = None,
        vector_profile: EmbeddingProfile | None = None,
        scope_context: ScopeContext | None = None,
    ) -> RecallCandidateBatch: ...

    async def save_recall_receipt(self, receipt: RecallReceipt) -> None: ...

    async def recent_recall_receipts(
        self, *, limit: int = 20, scope_context: ScopeContext | None = None
    ) -> list[RecallReceipt]: ...

    async def prune_recall_receipts(
        self, *, retain: int | None = None
    ) -> ReceiptPruneReport: ...

    async def integrity_report(self) -> IntegrityReport: ...

    async def list(
        self,
        *,
        kinds: list[MemoryKind] | None = None,
        scopes: list[Scope] | None = None,
        limit: int = 100,
        offset: int = 0,
        scope_context: ScopeContext | None = None,
    ) -> list[MemoryRecord]: ...

    async def lineage(
        self,
        record_id: str,
        *,
        scope_context: ScopeContext,
        as_of: datetime | None = None,
    ) -> list[MemoryRecord]: ...
