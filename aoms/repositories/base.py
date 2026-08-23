"""Repository protocol used by the transport-independent application layer."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from aoms.contracts import MemoryKind, MemoryRecord, Scope, SearchRequest, SearchResult


class MemoryRepository(Protocol):
    async def initialize(self) -> None: ...

    async def store(self, record: MemoryRecord) -> MemoryRecord: ...

    async def store_many(self, records: Sequence[MemoryRecord]) -> list[MemoryRecord]: ...

    async def get(self, record_id: str) -> MemoryRecord | None: ...

    async def search_by_keyword(self, request: SearchRequest) -> SearchResult: ...

    async def list(
        self,
        *,
        kinds: list[MemoryKind] | None = None,
        scopes: list[Scope] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]: ...
