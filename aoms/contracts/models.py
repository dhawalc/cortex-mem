"""Canonical Pydantic contracts shared by every AOMS transport adapter."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_RECORD_ID_LENGTH = 256
MAX_PROVENANCE_SOURCE_LENGTH = 2_048
MAX_CLAIM_KEY_LENGTH = 256
MAX_DERIVED_FROM_ENTRIES = 64
MAX_DERIVED_FROM_LENGTH = 256

# ``asserted_at`` is caller-declared. A small tolerance absorbs honest clock
# drift; anything beyond it is a forged-future freshness claim.
ASSERTED_AT_MAX_SKEW = timedelta(minutes=5)

# ``derived_from`` renders verbatim into a model's context through the recall
# provenance dump, so it accepts only opaque identifier shapes. Prose can never
# reach the notice channel through a field whose grammar excludes prose.
_IDENTIFIER_TOKEN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:+=@-]*\Z")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


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


class WriteDisposition(str, Enum):
    """The only two outcomes a write can have. There is no third."""

    ADMITTED = "admitted"
    CONTESTED = "contested"


class ContestTrigger(str, Enum):
    """Structural reason a write was routed to the ledger instead of the slot."""

    SLOT_COLLISION = "slot-collision"
    RETROGRADE = "retrograde-displacement"
    DERIVED = "derived-from-memory"
    POLICY_HOLD = "policy-hold"


class ContestResolution(str, Enum):
    """Named operator verdicts. Nothing else changes a durable disposition."""

    ADMIT = "admit"
    ADMIT_SUPERSEDING = "admit-superseding"
    SET_ASIDE = "set-aside"
    SPLIT = "split"


class ContestState(str, Enum):
    """Stored ledger states. ``expired-held`` is derived, never written."""

    OPEN = "open"
    RESOLVED = "resolved"


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


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clean_key(value: str, *, label: str, limit: int) -> str:
    if value != value.strip():
        raise ValueError(f"{label} must not have surrounding whitespace")
    if not value:
        raise ValueError(f"{label} must not be empty")
    if len(value) > limit:
        raise ValueError(f"{label} must be at most {limit} characters")
    if _CONTROL_CHARACTERS.search(value):
        raise ValueError(f"{label} must not contain control characters")
    return value


def validate_claim_key(value: str | None) -> str | None:
    """Bound the slot key so it stays a key in SQL, the CLI, and HTML."""

    if value is None:
        return None
    return _clean_key(value, label="claim_key", limit=MAX_CLAIM_KEY_LENGTH)


def validate_identifier(value: str | None, *, label: str) -> str | None:
    """Accept only opaque identifier shapes for caller-declared id fields."""

    if value is None:
        return None
    _clean_key(value, label=label, limit=MAX_RECORD_ID_LENGTH)
    if _IDENTIFIER_TOKEN.fullmatch(value) is None:
        raise ValueError(f"{label} must be an opaque identifier, not prose")
    return value


class Provenance(ContractModel):
    """Where a memory came from, without assuming a transport or filesystem."""

    source: str = Field(min_length=1, max_length=MAX_PROVENANCE_SOURCE_LENGTH)
    tier: str | None = None
    record_type: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    # When the claim was true, as distinct from when it was written.
    asserted_at: datetime | None = None
    # Recall receipt ids or memory ids this write was read out of. Declaring
    # one means the write can never displace a slot occupant.
    derived_from: list[str] = Field(default_factory=list)

    @field_validator("asserted_at")
    @classmethod
    def asserted_at_is_not_forged_future(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is None:
            return None
        normalized = _ensure_aware(value)
        if normalized > datetime.now(timezone.utc) + ASSERTED_AT_MAX_SKEW:
            raise ValueError("asserted_at must not be in the future")
        return normalized

    @field_validator("derived_from")
    @classmethod
    def derived_from_holds_identifiers(cls, values: list[str]) -> list[str]:
        if len(values) > MAX_DERIVED_FROM_ENTRIES:
            raise ValueError(
                f"derived_from accepts at most {MAX_DERIVED_FROM_ENTRIES} entries"
            )
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            _clean_key(
                value, label="derived_from entry", limit=MAX_DERIVED_FROM_LENGTH
            )
            if _IDENTIFIER_TOKEN.fullmatch(value) is None:
                raise ValueError(
                    "derived_from entries must be opaque identifiers, not prose"
                )
            if value not in seen:
                seen.add(value)
                normalized.append(value)
        return normalized


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
    # NULL means this record does not participate in the contest gate. Every
    # record written before migration 7 loads with NULL and keeps exactly the
    # semantics it had before the gate existed.
    claim_key: str | None = None
    disposition: WriteDisposition = WriteDisposition.ADMITTED
    observation_id: str | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        return _ensure_aware(value)

    @field_validator("claim_key")
    @classmethod
    def claim_key_is_a_clean_key(cls, value: str | None) -> str | None:
        return validate_claim_key(value)

    @field_validator("observation_id")
    @classmethod
    def observation_id_is_an_identifier(cls, value: str | None) -> str | None:
        return validate_identifier(value, label="observation_id")

    @model_validator(mode="after")
    def contested_records_occupy_a_slot(self) -> MemoryRecord:
        # A contest only exists relative to a claim slot. Records that do not
        # participate can never carry a contested disposition, so the legacy
        # opt-out cannot be turned into a disposition by any caller.
        if self.disposition is WriteDisposition.CONTESTED and self.claim_key is None:
            raise ValueError("a contested record must declare a claim_key")
        return self

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
        default=None,
        min_length=1,
        max_length=MAX_RECORD_ID_LENGTH,
        description=(
            "Stable id for this logical write. Reusing it makes a retry "
            "idempotent instead of creating a duplicate."
        ),
    )
    kind: MemoryKind
    content: str | dict[str, Any] | list[Any]
    tags: list[str] = Field(default_factory=list)
    scope: Scope = Scope.WORKSPACE
    provenance: Provenance | None = None
    supersedes: str | None = Field(
        default=None,
        description=(
            "Id of the record this one replaces. Set it whenever you are "
            "correcting or updating something already stored. If you also set "
            "claim_key and a record already answers that proposition, this is "
            "required: without it your write is kept in full but held as "
            "contested, and the existing record stays current until a person "
            "resolves it."
        ),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    claim_key: str | None = Field(
        default=None,
        description=(
            "Optional. Names the proposition this record answers, so AOMS can "
            "tell a declared replacement from a second, conflicting current "
            "answer to the same question. Use the same key for every record "
            "answering that question, and pair it with supersedes when "
            "replacing one. Omit it and this write behaves exactly as it did "
            "before claim slots existed."
        ),
    )
    observation_id: str | None = Field(
        default=None,
        description=(
            "Optional identifier grouping records that came from a single "
            "observation. Recorded for audit; it never affects admission."
        ),
    )
    # ``disposition`` is deliberately absent. ``extra="forbid"`` turns any
    # attempt to declare one into a boundary error, the same mechanism that
    # keeps scope identity out of tool arguments.

    @field_validator("claim_key")
    @classmethod
    def claim_key_is_a_clean_key(cls, value: str | None) -> str | None:
        return validate_claim_key(value)

    @field_validator("observation_id")
    @classmethod
    def observation_id_is_an_identifier(cls, value: str | None) -> str | None:
        return validate_identifier(value, label="observation_id")


class RememberResult(ContractModel):
    record: MemoryRecord
    created: bool
    disposition: WriteDisposition = WriteDisposition.ADMITTED
    contest_id: str | None = None
    incumbent_ids: list[str] = Field(default_factory=list)


class SupersedeRequest(ContractModel):
    content: str | dict[str, Any] | list[Any]
    id: str | None = Field(
        default=None, min_length=1, max_length=MAX_RECORD_ID_LENGTH
    )
    provenance: Provenance | None = None
    claim_key: str | None = None

    @field_validator("claim_key")
    @classmethod
    def claim_key_is_a_clean_key(cls, value: str | None) -> str | None:
        return validate_claim_key(value)


class SearchRequest(ContractModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    kinds: list[MemoryKind] | None = None
    scopes: list[Scope] | None = None
    include_contested: bool = False


class ContestEntry(ContractModel):
    """One durable ledger row. Every identifier here is server-generated."""

    contest_id: str
    record_id: str
    claim_key: str | None = None
    observation_id: str | None = None
    scope: Scope
    scope_agent_id: str | None = None
    scope_workspace_id: str | None = None
    incumbent_ids: list[str] = Field(default_factory=list)
    trigger: ContestTrigger
    trigger_detail: dict[str, Any] = Field(default_factory=dict)
    occurrence_count: int = Field(default=1, ge=1)
    opened_at: datetime
    opened_by_agent_id: str
    state: ContestState = ContestState.OPEN
    resolution: ContestResolution | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None
    escalated_at: datetime | None = None

    @field_validator("opened_at", "resolved_at", "escalated_at")
    @classmethod
    def contest_timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        return _ensure_aware(value) if value is not None else None


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
    # How many open contests stand against this source's claim slot. An
    # integer, never challenger text.
    contested_count: int = Field(default=0, ge=0)

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
    # ``memories.contested`` is a denormalized projection of the ledger. Like
    # the FTS projection it can only be trusted while it provably agrees.
    contested_projection_drift: list[str] = Field(default_factory=list)
    contested_count: int = Field(default=0, ge=0)
    open_contest_count: int = Field(default=0, ge=0)
