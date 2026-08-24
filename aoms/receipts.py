"""Versioned, transport-independent recall receipts.

Receipts are intentionally composed only of stable Pydantic/JSON primitives so
the launch relay and the generated "Anatomy" report can consume them without
depending on an internal ranker class. Additive fields may be introduced under
schema version 1; a breaking rename or semantic change requires version 2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, field_validator

from aoms.contracts.models import (
    ContestTrigger,
    ContractModel,
    MemoryKind,
    Scope,
    WriteDisposition,
)
from aoms.version import __version__

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
    agent_id: str | None = None
    workspace_id: str | None = None
    query: str
    scopes: list[Scope] | None
    kinds: list[MemoryKind] | None
    token_budget: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    scope_filtered_count: int = Field(default=0, ge=0)
    top_candidates: list[CandidateScore]
    rejected_sample: list[CandidateScore]
    selected: list[SelectedMemory]
    supersession_resolution: bool = True
    superseded_suppressed: list[str] = Field(default_factory=list)
    # Additive v1 evidence: older receipts remain readable, while new receipts
    # retain the exact provenance-fenced artifact shown to the model.
    context: str | None = None
    total_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    engine_version: str
    vector_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    # Additive v1 contest evidence. A recall that can withhold anything must
    # name both what it withheld and the configuration that decided to, or it
    # is no longer a complete explanation of its own output.
    contested_withheld: list[str] = Field(default_factory=list)
    contested_incumbents: dict[str, int] = Field(default_factory=dict)
    ruleset_digest: str | None = None

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class WriteReceipt(ContractModel):
    """Stable JSON evidence for one write-admission decision.

    Append-only and exempt from recall-receipt retention: the ledger's copy of
    a decision is never trimmed by a background mechanism. ``trigger_detail``
    carries integers, ids and timestamps only.
    """

    schema_version: Literal[1] = RECEIPT_SCHEMA_VERSION
    receipt_id: str
    created_at: datetime
    record_id: str
    claim_key: str | None = None
    agent_id: str | None = None
    workspace_id: str | None = None
    kind: MemoryKind
    scope: Scope
    content_sha256: str
    incumbent_ids: list[str] = Field(default_factory=list)
    disposition: WriteDisposition
    trigger: ContestTrigger | None = None
    trigger_detail: dict[str, Any] = Field(default_factory=dict)
    contest_id: str | None = None
    asserted_at: datetime | None = None
    derived_from: list[str] = Field(default_factory=list)
    ruleset_digest: str
    occurrence_count: int = Field(default=1, ge=1)
    engine_version: str = ENGINE_VERSION

    @field_validator("created_at", "asserted_at")
    @classmethod
    def write_timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None


__all__ = [
    "ENGINE_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "CandidateScore",
    "RecallReceipt",
    "ScoreComponent",
    "SelectedMemory",
    "WriteReceipt",
]
