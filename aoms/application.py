"""Transport-independent application service for AOMS v2."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from aoms.contracts import (
    MemoryRecord,
    Provenance,
    RecallRequest,
    RecallResult,
    RememberRequest,
    RememberResult,
    SearchRequest,
    SearchResult,
)
from aoms.repositories.base import MemoryRepository


class AOMSApplication:
    def __init__(self, repository: MemoryRepository):
        self.repository = repository

    async def remember(self, request: RememberRequest) -> RememberResult:
        await self.repository.initialize()
        record_id = request.id or str(uuid4())
        existing = await self.repository.get(record_id)
        now = datetime.now(timezone.utc)
        record = MemoryRecord(
            id=record_id,
            kind=request.kind,
            content=request.content,
            tags=request.tags,
            scope=request.scope,
            provenance=request.provenance or Provenance(source="application"),
            created_at=existing.created_at if existing else now,
            updated_at=now,
            supersedes=request.supersedes,
            metadata=request.metadata,
        )
        await self.repository.store(record)
        return RememberResult(record=record, created=existing is None)

    async def search(self, request: SearchRequest) -> SearchResult:
        return await self.repository.search_by_keyword(request)

    async def recall(self, request: RecallRequest) -> RecallResult:
        raise NotImplementedError(
            "The recall engine is intentionally deferred to the next AOMS core slice."
        )
