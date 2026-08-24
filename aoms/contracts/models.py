"""Canonical Pydantic contracts shared by every AOMS transport adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_RECORD_ID_LENGTH = 256
MAX_PROVENANCE_SOURCE_LENGTH = 2_048


class ContractModel(BaseModel):
    """Strict base model so adapter mistakes fail at the system boundary."""

    model_config = ConfigDict(extra="forbid")


class MemoryKind(str, Enum):
    """Closed set of canonical memory kinds."""

    EPISODE = "episode"
    DECISION = "decision"
    FAILURE = "failure"
    FACT = "fact"
    ENTITY = "entity"
    RELATION = "relation"
    PROCEDURE = "procedure"
    PATTERN = "pattern"


class Scope(str, Enum):
    """Visibility boundary applied to a memory record."""

    AGENT_PRIVATE = "agent-private"
    WORKSPACE = "workspace"
    USER_GLOBAL = "user-global"


class ScopeContext(ContractModel):
    """Authenticated/process-bound identity used to enforce memory visibility."""

    agent_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)

    @field_validator("agent_id", "workspace_id")
    @classmethod
    def identifiers_are_clean(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("scope identifiers must not have surrounding whitespace")
        return value


class Provenance(ContractModel):
    """Where a memory came from, without assuming a transport or filesystem."""

    source: str = Field(min_length=1, max_length=MAX_PROVENANCE_SOURCE_LENGTH)
    tier: str | None = None
    record_type: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class MemoryRecord(ContractModel):
    """Canonical persisted representation of one AOMS memory."""

    id: str = Field(min_length=1, max_length=MAX_RECORD_ID_LENGTH)
    kind: MemoryKind
    content: str | dict[str, Any] | list[Any]
    tags: list[str] = Field(default_factory=list)
    scope: Scope = Scope.WORKSPACE
    scope_agent_id: str | None = None
    scope_workspace_id: str | None = None
    created_by_agent_id: str | None = None
    provenance: Provenance
    created_at: datetime
    updated_at: datetime
    supersedes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        return _ensure_aware(value)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            clean = tag.strip()
            if clean and clean not in seen:
                normalized.append(clean)
                seen.add(clean)
        return normalized

    @model_validator(mode="after")
    def updated_not_before_created(self) -> MemoryRecord:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        return self


class RememberRequest(ContractModel):
    id: str | None = Field(
        default=None, min_length=1, max_length=MAX_RECORD_ID_LENGTH
    )
    kind: MemoryKind
    content: str | dict[str, Any] | list[Any]
    tags: list[str] = Field(default_factory=list)
    scope: Scope = Scope.WORKSPACE
    provenance: Provenance | None = None
    supersedes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RememberResult(ContractModel):
    record: MemoryRecord
    created: bool


class SupersedeRequest(ContractModel):
    content: str | dict[str, Any] | list[Any]
    id: str | None = Field(
        default=None, min_length=1, max_length=MAX_RECORD_ID_LENGTH
    )
    provenance: Provenance | None = None


class SearchRequest(ContractModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    kinds: list[MemoryKind] | None = None
    scopes: list[Scope] | None = None


class SearchHit(ContractModel):
    record: MemoryRecord
    score: float = Field(ge=0.0)


class SearchResult(ContractModel):
    items: list[SearchHit]
    total: int = Field(ge=0)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class RecallRequest(ContractModel):
    task: str = Field(min_length=1)
    token_budget: int = Field(default=2_000, ge=1, le=100_000)
    scopes: list[Scope] | None = None
    kinds: list[MemoryKind] | None = None


class RecallSource(ContractModel):
    memory_id: str
    kind: MemoryKind
    provenance: Provenance
    excerpt: str | None = None
    scope: Scope | None = None
    timestamp: datetime | None = None
    token_count: int | None = Field(default=None, ge=0)
    score: float | None = Field(default=None, ge=0.0)
    truncated: bool = False

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_utc(cls, value: datetime | None) -> datetime | None:
        return _ensure_aware(value) if value is not None else None


class RecallResult(ContractModel):
    context: str
    sources: list[RecallSource]
    token_count: int = Field(ge=0)
    truncated: bool
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ReceiptPruneReport(ContractModel):
    retained_limit: int = Field(ge=0)
    deleted_count: int = Field(ge=0)
    remaining_count: int = Field(ge=0)


class IntegrityReport(ContractModel):
    """Typed, non-mutating comparison of canonical and derived storage."""

    healthy: bool
    memory_count: int = Field(ge=0)
    fts_count: int = Field(ge=0)
    vector_count: int = Field(ge=0)
    vector_table_counts: dict[str, int] = Field(default_factory=dict)
    missing_fts_memory_ids: list[str] = Field(default_factory=list)
    orphan_fts_memory_ids: list[str] = Field(default_factory=list)
    orphan_vector_memory_ids: list[str] = Field(default_factory=list)
    unscoped_memory_ids: list[str] = Field(default_factory=list)
