"""Durable embedding queue worker shared by the app and backfill tool."""

from __future__ import annotations

from dataclasses import dataclass

from aoms.embeddings import EmbeddingProvider, text_for_embedding
from aoms.repositories.base import CompletedEmbedding, VectorRepository


@dataclass(frozen=True, slots=True)
class EmbeddingSweepResult:
    claimed: int = 0
    embedded: int = 0
    failed: int = 0
    batches: int = 0

    def plus(self, other: EmbeddingSweepResult) -> EmbeddingSweepResult:
        return EmbeddingSweepResult(
            claimed=self.claimed + other.claimed,
            embedded=self.embedded + other.embedded,
            failed=self.failed + other.failed,
            batches=self.batches + other.batches,
        )


async def sweep_pending_embeddings(
    repository: VectorRepository,
    provider: EmbeddingProvider,
    *,
    batch_size: int = 64,
    max_batches: int | None = None,
    lease_seconds: int = 300,
) -> EmbeddingSweepResult:
    """Embed leased queue rows; every completion is idempotent and transactional."""

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if max_batches is not None and max_batches < 1:
        raise ValueError("max_batches must be at least 1")
    profile = provider.profile
    if profile is None:
        return EmbeddingSweepResult()

    result = EmbeddingSweepResult()
    while max_batches is None or result.batches < max_batches:
        pending = await repository.claim_pending_embeddings(
            profile, limit=batch_size, lease_seconds=lease_seconds
        )
        if not pending:
            break
        batch_result = EmbeddingSweepResult(claimed=len(pending), batches=1)
        try:
            vectors = await provider.embed_documents(
                [text_for_embedding(item.record) for item in pending]
            )
            if len(vectors) != len(pending):
                raise RuntimeError("embedding provider returned the wrong batch length")
        except Exception as exc:  # noqa: BLE001 - provider boundary is third-party
            await repository.fail_pending_embeddings(pending, repr(exc))
            result = result.plus(
                EmbeddingSweepResult(
                    claimed=len(pending), failed=len(pending), batches=1
                )
            )
            break

        completed = [
            CompletedEmbedding(pending=item, vector=vector)
            for item, vector in zip(pending, vectors, strict=True)
            if vector is not None
        ]
        missing = [
            item
            for item, vector in zip(pending, vectors, strict=True)
            if vector is None
        ]
        try:
            embedded = await repository.complete_pending_embeddings(completed)
        except Exception as exc:  # noqa: BLE001 - extension boundary is third-party
            await repository.fail_pending_embeddings(pending, repr(exc))
            result = result.plus(
                EmbeddingSweepResult(
                    claimed=len(pending), failed=len(pending), batches=1
                )
            )
            break
        if missing:
            await repository.fail_pending_embeddings(
                missing, "embedding provider returned no vector"
            )
        batch_result = EmbeddingSweepResult(
            claimed=batch_result.claimed,
            embedded=embedded,
            failed=len(missing),
            batches=1,
        )
        result = result.plus(batch_result)
        if missing:
            break
    return result


__all__ = ["EmbeddingSweepResult", "sweep_pending_embeddings"]
