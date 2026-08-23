"""Interruptible, bounded-memory embedding backfill for explicit databases.

The scanner advances by record ID in fixed batches. Queue insertion and vector
completion are idempotent, so interruption needs no sidecar checkpoint: reruns
skip vectors whose embedded record revision is current and resume durable queue
rows first. The CLI deliberately requires ``--db`` rather than silently using
the default data directory.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from aoms.embedding_jobs import sweep_pending_embeddings
from aoms.embeddings import EmbeddingProvider, provider_from_config
from aoms.repositories.base import VectorRepository
from aoms.repositories.sqlite import SQLiteMemoryRepository


@dataclass(frozen=True, slots=True)
class BackfillProgress:
    phase: str
    scanned: int
    queued: int
    embedded: int
    failed: int
    pending: int


@dataclass(frozen=True, slots=True)
class BackfillResult:
    scanned: int = 0
    queued: int = 0
    embedded: int = 0
    failed: int = 0
    batches: int = 0
    pending: int = 0


async def backfill_embeddings(
    repository: VectorRepository,
    provider: EmbeddingProvider,
    *,
    batch_size: int = 64,
    progress: Callable[[BackfillProgress], None] | None = None,
    max_batches: int | None = None,
) -> BackfillResult:
    """Embed missing/stale records, safely resumable after every committed batch."""

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if max_batches is not None and max_batches < 1:
        raise ValueError("max_batches must be at least 1")
    profile = provider.profile
    if profile is None:
        return BackfillResult()

    scanned = queued = embedded = failed = batches = 0

    async def emit(phase: str) -> int:
        pending = await repository.pending_embedding_count(profile)
        if progress is not None:
            progress(
                BackfillProgress(
                    phase=phase,
                    scanned=scanned,
                    queued=queued,
                    embedded=embedded,
                    failed=failed,
                    pending=pending,
                )
            )
        return pending

    # Finish durable leftovers before scanning; this is the common resume path.
    while max_batches is None or batches < max_batches:
        sweep = await sweep_pending_embeddings(
            repository, provider, batch_size=batch_size, max_batches=1
        )
        embedded += sweep.embedded
        failed += sweep.failed
        batches += sweep.batches
        if sweep.claimed == 0 or sweep.failed:
            break
        await emit("embedding")
    if failed or (max_batches is not None and batches >= max_batches):
        pending = await emit("interrupted" if not failed else "failed")
        return BackfillResult(scanned, queued, embedded, failed, batches, pending)

    after_id: str | None = None
    while True:
        records, next_id, examined = await repository.scan_records_for_embedding(
            profile, after_id=after_id, limit=batch_size
        )
        if next_id is None:
            break
        scanned += examined
        queued += await repository.enqueue_unembedded(records, profile)
        await emit("scanning")
        after_id = next_id

        if records:
            sweep = await sweep_pending_embeddings(
                repository, provider, batch_size=batch_size, max_batches=1
            )
            embedded += sweep.embedded
            failed += sweep.failed
            batches += sweep.batches
            await emit("embedding")
            if sweep.failed or (max_batches is not None and batches >= max_batches):
                break

    pending = await emit(
        "complete"
        if not failed and pending_limit_ok(batches, max_batches)
        else "interrupted"
    )
    return BackfillResult(scanned, queued, embedded, failed, batches, pending)


def pending_limit_ok(batches: int, max_batches: int | None) -> bool:
    return max_batches is None or batches < max_batches


def _print_progress(item: BackfillProgress) -> None:
    print(
        f"{item.phase}: scanned={item.scanned} queued={item.queued} "
        f"embedded={item.embedded} failed={item.failed} pending={item.pending}",
        flush=True,
    )


async def _run_cli(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    repository = SQLiteMemoryRepository(args.db)
    provider = provider_from_config(environ)
    result = await backfill_embeddings(
        repository,
        provider,
        batch_size=args.batch_size,
        progress=_print_progress,
    )
    return 1 if result.failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="AOMS SQLite database")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args(argv)
    return asyncio.run(_run_cli(args, os.environ))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["BackfillProgress", "BackfillResult", "backfill_embeddings", "main"]
