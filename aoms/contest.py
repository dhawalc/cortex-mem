"""The content-free write-admission decision, and the ruleset that governs it.

``decide`` is the whole gate. It is a pure, total function over two frozen
value objects and a clock reading. It has no repository handle, no counters,
no history, and — structurally, by signature — no way to see record text. The
only thing it ever learns about content is a SHA-256 digest, which supports
exactly one comparison: identical or not.

That is not a promise in a comment. ``WriteIntent`` has no content field, so
"AOMS does not judge content" is enforced by the type, and a test asserts the
signature carries no ``content`` parameter and no repository annotation.

There are exactly two dispositions. A contested write is stored in full and
stays durable and searchable; it simply does not hold the slot and does not
pack into recall. Nothing here refuses a write, discards evidence, or edits
anything.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from aoms.contracts import (
    ContestTrigger,
    MemoryKind,
    Scope,
    WriteDisposition,
)

# Bumped when the meaning of a trigger changes, so a stored digest can never
# silently describe different behaviour than the one that produced it.
RULESET_VERSION = 1

# T4 is a seam, not a rule. No classifier ships in v1, and nothing but a named
# human resolution ever changes a durable disposition.
V1_TRIGGERS: frozenset[ContestTrigger] = frozenset(
    {
        ContestTrigger.SLOT_COLLISION,
        ContestTrigger.RETROGRADE,
        ContestTrigger.DERIVED,
    }
)


def content_digest(content: object) -> str:
    """Hash content once, at the boundary, so the gate never sees the text."""

    if isinstance(content, str):
        payload = content
    else:
        payload = json.dumps(content, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Ruleset:
    """The contest configuration in force, identified by a stable digest.

    The digest is stamped on every write receipt *and* on every recall
    receipt. Once anything can be withheld from packing, the same store under
    two configurations packs different context, so a recall receipt that does
    not name its configuration has stopped being a complete explanation of its
    own output.
    """

    version: int = RULESET_VERSION
    enabled_triggers: frozenset[ContestTrigger] = V1_TRIGGERS
    contest_sla_days: int = 14
    contest_expiry_days: int = 30

    def __post_init__(self) -> None:
        if self.contest_sla_days < 1:
            raise ValueError("contest_sla_days must be at least 1")
        if self.contest_expiry_days < self.contest_sla_days:
            raise ValueError("contest_expiry_days must not precede the SLA")
        if ContestTrigger.POLICY_HOLD in self.enabled_triggers:
            raise ValueError("policy-hold is a seam; no rule ships in v1")

    @property
    def digest(self) -> str:
        canonical = json.dumps(
            {
                "version": self.version,
                "enabled_triggers": sorted(
                    trigger.value for trigger in self.enabled_triggers
                ),
                "contest_sla_days": self.contest_sla_days,
                "contest_expiry_days": self.contest_expiry_days,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


DEFAULT_RULESET = Ruleset()


@dataclass(frozen=True, slots=True)
class WriteIntent:
    """Everything the gate may know about a write. Note the absence."""

    kind: MemoryKind
    scope: Scope
    content_sha256: str
    claim_key: str | None = None
    supersedes: str | None = None
    asserted_at: datetime | None = None
    derived_from: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SlotOccupant:
    """One admitted record currently holding a claim slot."""

    record_id: str
    content_sha256: str
    asserted_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SlotState:
    """The admitted occupants of one claim slot at decision time."""

    occupants: tuple[SlotOccupant, ...] = ()

    @property
    def occupied(self) -> bool:
        return bool(self.occupants)


@dataclass(frozen=True, slots=True)
class Decision:
    """The gate's verdict, carrying only integers, ids and timestamps."""

    disposition: WriteDisposition
    trigger: ContestTrigger | None = None
    incumbent_ids: tuple[str, ...] = ()
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def contested(self) -> bool:
        return self.disposition is WriteDisposition.CONTESTED


_ADMITTED = Decision(disposition=WriteDisposition.ADMITTED)


def decide(
    intent: WriteIntent,
    slot: SlotState,
    *,
    now: datetime,
    ruleset: Ruleset = DEFAULT_RULESET,
) -> Decision:
    """Route one write to the slot or to the ledger. Never refuses either one.

    ``now`` is accepted for trigger arithmetic and to keep the function total
    without reading a clock of its own. ``ruleset`` selects which triggers are
    in force; it is frozen, content-free configuration, and the digest of the
    ruleset actually used is recorded on the resulting receipt.
    """

    if intent.claim_key is None:
        # The migration sentinel, in the write path. A record that declares no
        # slot cannot collide with one, so no trigger can fire and behaviour
        # is byte-identical to the day before the gate existed.
        return _ADMITTED
    if not slot.occupied:
        return _ADMITTED

    incumbent_ids = tuple(sorted(occupant.record_id for occupant in slot.occupants))

    # Identical content on an occupied slot is corroboration, never a contest.
    if all(
        occupant.content_sha256 == intent.content_sha256
        for occupant in slot.occupants
    ):
        return Decision(
            disposition=WriteDisposition.ADMITTED,
            incumbent_ids=incumbent_ids,
            detail={"corroboration": True},
        )

    enabled = ruleset.enabled_triggers

    # T3 — derived-from-memory. Checked first because it is the strongest
    # statement available: content that came out of memory can never displace
    # what is in memory, whatever else the write declares. This is what blocks
    # laundering, where an agent reads crafted memory and re-asserts it.
    if ContestTrigger.DERIVED in enabled and intent.derived_from:
        return Decision(
            disposition=WriteDisposition.CONTESTED,
            trigger=ContestTrigger.DERIVED,
            incumbent_ids=incumbent_ids,
            detail={"derived_from_count": len(intent.derived_from)},
        )

    # T2 — retrograde displacement. Two caller-declared timestamps compared
    # numerically. No text is parsed to find them.
    if ContestTrigger.RETROGRADE in enabled and intent.asserted_at is not None:
        older_than = tuple(
            occupant.record_id
            for occupant in slot.occupants
            if occupant.asserted_at is not None
            and intent.asserted_at < occupant.asserted_at
        )
        if older_than:
            return Decision(
                disposition=WriteDisposition.CONTESTED,
                trigger=ContestTrigger.RETROGRADE,
                incumbent_ids=incumbent_ids,
                detail={
                    "retrograde_incumbent_count": len(older_than),
                    "asserted_at": intent.asserted_at.isoformat(),
                },
            )

    # T1 — slot collision. An occupied slot, different content, and no
    # declared supersession of the occupant.
    if ContestTrigger.SLOT_COLLISION in enabled:
        undeclared = tuple(
            occupant.record_id
            for occupant in slot.occupants
            if occupant.record_id != intent.supersedes
        )
        if undeclared:
            return Decision(
                disposition=WriteDisposition.CONTESTED,
                trigger=ContestTrigger.SLOT_COLLISION,
                incumbent_ids=incumbent_ids,
                detail={"undeclared_incumbent_count": len(undeclared)},
            )

    # A declared supersession of every occupant is an ordinary correction.
    return Decision(
        disposition=WriteDisposition.ADMITTED,
        incumbent_ids=incumbent_ids,
        detail={"declared_supersession": True},
    )


def is_overdue(opened_at: datetime, *, now: datetime, ruleset: Ruleset) -> bool:
    return (now - opened_at).days >= ruleset.contest_sla_days


def is_expired_held(opened_at: datetime, *, now: datetime, ruleset: Ruleset) -> bool:
    """Derived reporting state. Never stored, because nothing expires on a timer."""

    return (now - opened_at).days >= ruleset.contest_expiry_days


__all__ = [
    "DEFAULT_RULESET",
    "RULESET_VERSION",
    "V1_TRIGGERS",
    "Decision",
    "Ruleset",
    "SlotOccupant",
    "SlotState",
    "WriteIntent",
    "content_digest",
    "decide",
    "is_expired_held",
    "is_overdue",
]
