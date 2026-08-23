"""Canonical, transport-independent AOMS v2 contracts."""

from aoms.contracts.errors import ErrorCode, ErrorDetail, ErrorResponse
from aoms.contracts.models import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallRequest,
    RecallResult,
    RecallSource,
    RememberRequest,
    RememberResult,
    Scope,
    SearchHit,
    SearchRequest,
    SearchResult,
)

__all__ = [
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "MemoryKind",
    "MemoryRecord",
    "Provenance",
    "RecallRequest",
    "RecallResult",
    "RecallSource",
    "RememberRequest",
    "RememberResult",
    "Scope",
    "SearchHit",
    "SearchRequest",
    "SearchResult",
]
