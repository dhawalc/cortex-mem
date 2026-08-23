"""Versioned, transport-independent recall receipts.

Receipts are intentionally composed only of stable Pydantic/JSON primitives so
the launch relay and the generated "Anatomy" report can consume them without
depending on an internal ranker class. Additive fields may be introduced under
schema version 1; a breaking rename or semantic change requires version 2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, field_validator

from aoms.contracts.models import ContractModel, MemoryKind, Scope
from cortex_mem.__version__ import __version__

RECEIPT_SCHEMA_VERSION = 1
ENGINE_VERSION = __version__


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ScoreComponent(ContractModel):
    """One independently replaceable scorer's calibrated contribution."""

    raw: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0)
    contribution: float = Field(ge=0.0)


class CandidateScore(ContractModel):
    memory_id: str
    kind: MemoryKind
    scope: Scope
    updated_at: datetime
    retrieval_sources: list[str]
    total_score: float = Field(ge=0.0)
    breakdown: dict[str, ScoreComponent]
    selected: bool
    rejection_reason: str | None = None

    @field_validator("updated_at")
    @classmethod
    def updated_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class SelectedMemory(ContractModel):
    memory_id: str
    token_cost: int = Field(ge=0)
    truncated: bool


class RecallReceipt(ContractModel):
    """Stable JSON evidence for one recall decision."""

    schema_version: Literal[1] = RECEIPT_SCHEMA_VERSION
    receipt_id: str
    created_at: datetime
    query: str
    scopes: list[Scope] | None
    kinds: list[MemoryKind] | None
    token_budget: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    top_candidates: list[CandidateScore]
    rejected_sample: list[CandidateScore]
    selected: list[SelectedMemory]
    total_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    engine_version: str
    vector_coverage: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value)


__all__ = [
    "ENGINE_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "CandidateScore",
    "RecallReceipt",
    "ScoreComponent",
    "SelectedMemory",
]
