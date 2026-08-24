"""Persistence interfaces and implementations for AOMS v2."""

from aoms.repositories.base import (
    CompletedEmbedding,
    ConditionalStoreResult,
    MemoryRepository,
    PendingEmbedding,
    RecordContentConflictError,
    RecallCandidate,
    RecallCandidateBatch,
    VectorHit,
    VectorRepository,
)
from aoms.repositories.sqlite import SQLiteMemoryRepository

__all__ = [
    "CompletedEmbedding",
    "ConditionalStoreResult",
    "MemoryRepository",
    "PendingEmbedding",
    "RecordContentConflictError",
    "RecallCandidate",
    "RecallCandidateBatch",
    "SQLiteMemoryRepository",
    "VectorHit",
    "VectorRepository",
]
