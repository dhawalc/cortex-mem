"""Repository protocol used by the transport-independent application layer."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    RecallRequest,
    Scope,
    SearchRequest,
    SearchResult,
)
from aoms.receipts import RecallReceipt


@dataclass(frozen=True, slots=True)
class RecallCandidate:
    """Repository-neutral candidate evidence consumed by recall scorers."""

    record: MemoryRecord
    fts_score: float
    retrieval_sources: tuple[str, ...]


class MemoryRepository(Protocol):
    async def initialize(self) -> None: ...

    async def store(self, record: MemoryRecord) -> MemoryRecord: ...

    async def store_many(self, records: Sequence[MemoryRecord]) -> list[MemoryRecord]: ...

    async def get(self, record_id: str) -> MemoryRecord | None: ...

    async def search_by_keyword(self, request: SearchRequest) -> SearchResult: ...

    async def retrieve_recall_candidates(
        self, request: RecallRequest, *, limit: int = 100
    ) -> list[RecallCandidate]: ...

    async def save_recall_receipt(self, receipt: RecallReceipt) -> None: ...

    async def recent_recall_receipts(self, *, limit: int = 20) -> list[RecallReceipt]: ...

    async def list(
        self,
        *,
        kinds: list[MemoryKind] | None = None,
        scopes: list[Scope] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]: ...
