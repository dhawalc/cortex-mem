"""Persistence interfaces and implementations for AOMS v2."""

from aoms.repositories.base import (
    CompletedEmbedding,
    MemoryRepository,
    PendingEmbedding,
    RecallCandidate,
    VectorHit,
    VectorRepository,
)
from aoms.repositories.sqlite import SQLiteMemoryRepository

__all__ = [
    "CompletedEmbedding",
    "MemoryRepository",
    "PendingEmbedding",
    "RecallCandidate",
    "SQLiteMemoryRepository",
    "VectorHit",
    "VectorRepository",
]
