"""Canonical, transport-independent AOMS v2 contracts."""

from aoms.contracts.errors import ErrorCode, ErrorDetail, ErrorResponse
from aoms.contracts.models import (
    MemoryKind,
    MemoryRecord,
    IntegrityReport,
    Provenance,
    RecallRequest,
    RecallResult,
    RecallSource,
    ReceiptPruneReport,
    RememberRequest,
    RememberResult,
    SupersedeRequest,
    Scope,
    ScopeContext,
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
    "IntegrityReport",
    "Provenance",
    "RecallRequest",
    "RecallResult",
    "RecallSource",
    "ReceiptPruneReport",
    "RememberRequest",
    "RememberResult",
    "SupersedeRequest",
    "Scope",
    "ScopeContext",
    "SearchHit",
    "SearchRequest",
    "SearchResult",
]
