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
from aoms.receipts import RecallReceipt
from aoms.recall import RecallEngine


class AOMSApplication:
    def __init__(
        self,
        repository: MemoryRepository,
        *,
        receipt_repository: MemoryRepository | None = None,
        recall_engine: RecallEngine | None = None,
    ):
        self.repository = repository
        self.receipt_repository = receipt_repository or repository
        self.recall_engine = recall_engine or RecallEngine(
            repository, self.receipt_repository
        )

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
        return await self.recall_engine.recall(request)

    async def recent_recall_receipts(self, *, limit: int = 20) -> list[RecallReceipt]:
        """Return newest receipts for inspection and generated proof artifacts."""

        return await self.receipt_repository.recent_recall_receipts(limit=limit)
