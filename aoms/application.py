"""Transport-independent application service for AOMS v2."""

from __future__ import annotations

import asyncio
import logging
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
from aoms.embedding_jobs import EmbeddingSweepResult, sweep_pending_embeddings
from aoms.embeddings import EmbeddingProvider, FastEmbedProvider
from aoms.recall import RecallEngine
from aoms.receipts import RecallReceipt
from aoms.repositories.base import MemoryRepository, VectorRepository

logger = logging.getLogger(__name__)


class AOMSApplication:
    def __init__(
        self,
        repository: MemoryRepository,
        *,
        receipt_repository: MemoryRepository | None = None,
        recall_engine: RecallEngine | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        background_embeddings: bool = True,
    ):
        self.repository = repository
        self.receipt_repository = receipt_repository or repository
        self.embedding_provider = embedding_provider or FastEmbedProvider()
        self.background_embeddings = background_embeddings
        self._embedding_tasks: set[asyncio.Task[EmbeddingSweepResult]] = set()
        self.recall_engine = recall_engine or RecallEngine(
            repository,
            self.receipt_repository,
            embedding_provider=self.embedding_provider,
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
        if self.embedding_provider.profile is not None and isinstance(
            self.repository, VectorRepository
        ):
            await self.repository.store_with_embedding_pending(
                record, self.embedding_provider.profile
            )
            if self.background_embeddings:
                task = asyncio.create_task(
                    self.catch_up_embeddings(batch_size=1, max_batches=1),
                    name=f"aoms-embed-{record.id}",
                )
                self._embedding_tasks.add(task)
                task.add_done_callback(self._embedding_task_done)
        else:
            await self.repository.store(record)
        return RememberResult(record=record, created=existing is None)

    async def catch_up_embeddings(
        self, *, batch_size: int = 64, max_batches: int | None = None
    ) -> EmbeddingSweepResult:
        """Drain durable pending work; safe for periodic CLI/orchestrator sweeps."""

        if not isinstance(self.repository, VectorRepository):
            return EmbeddingSweepResult()
        return await sweep_pending_embeddings(
            self.repository,
            self.embedding_provider,
            batch_size=batch_size,
            max_batches=max_batches,
        )

    async def wait_for_background_embeddings(self) -> None:
        """Testing/shutdown hook; remember itself never awaits provider work."""

        if self._embedding_tasks:
            await asyncio.gather(*tuple(self._embedding_tasks), return_exceptions=True)

    def _embedding_task_done(self, task: asyncio.Task[EmbeddingSweepResult]) -> None:
        self._embedding_tasks.discard(task)
        try:
            task.result()
        except Exception:  # pragma: no cover - final defensive task boundary
            logger.exception(
                "background embedding sweep failed; durable work remains queued"
            )

    async def search(self, request: SearchRequest) -> SearchResult:
        return await self.repository.search_by_keyword(request)

    async def recall(self, request: RecallRequest) -> RecallResult:
        return await self.recall_engine.recall(request)

    async def recent_recall_receipts(self, *, limit: int = 20) -> list[RecallReceipt]:
        """Return newest receipts for inspection and generated proof artifacts."""

        return await self.receipt_repository.recent_recall_receipts(limit=limit)
