"""Auditable ownership assignment contracts for legacy, unscoped records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from aoms.contracts import Scope

ASSIGNMENT_REASON = "legacy-import bulk assignment 2026-08-23"
LEGACY_IMPORT_ACTOR = "legacy-import"
UNSCOPED_SQL = (
    "created_by_agent_id IS NULL OR "
    "(scope = 'agent-private' AND scope_agent_id IS NULL) OR "
    "(scope = 'workspace' AND scope_workspace_id IS NULL)"
)


@dataclass(frozen=True, slots=True)
class OwnershipSnapshot:
    """Distribution of records that still lack a valid ownership assignment."""

    unscoped_records: int
    by_kind: dict[str, int]
    by_tier: dict[str, int]


@dataclass(frozen=True, slots=True)
class OwnershipReport:
    """Machine-readable result of one dry-run or executing assignment."""

    scope: str
    dry_run: bool
    batch_size: int
    assignment_timestamp: str
    tool_version: str
    reason: str
    would_assign: int
    assigned_records: int
    remaining_unscoped: int
    before: OwnershipSnapshot
    after: OwnershipSnapshot

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class OwnershipRepository(Protocol):
    async def ownership_snapshot(self) -> OwnershipSnapshot: ...

    async def assign_unscoped_user_global_batch(
        self,
        *,
        limit: int,
        assignment_timestamp: str,
        tool_version: str,
        reason: str,
    ) -> int: ...


async def assign_ownership(
    repository: OwnershipRepository,
    *,
    scope: Scope,
    dry_run: bool,
    batch_size: int,
    assignment_timestamp: str,
    tool_version: str,
    reason: str = ASSIGNMENT_REASON,
) -> OwnershipReport:
    """Assign every currently unscoped record in independently committed batches."""

    if scope is not Scope.USER_GLOBAL:
        raise ValueError("bulk ownership assignment only supports user-global")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    before = await repository.ownership_snapshot()
    assigned = 0
    if not dry_run:
        while True:
            batch_assigned = await repository.assign_unscoped_user_global_batch(
                limit=batch_size,
                assignment_timestamp=assignment_timestamp,
                tool_version=tool_version,
                reason=reason,
            )
            assigned += batch_assigned
            if batch_assigned == 0:
                break
    after = await repository.ownership_snapshot()
    return OwnershipReport(
        scope=scope.value,
        dry_run=dry_run,
        batch_size=batch_size,
        assignment_timestamp=assignment_timestamp,
        tool_version=tool_version,
        reason=reason,
        would_assign=before.unscoped_records,
        assigned_records=assigned,
        remaining_unscoped=after.unscoped_records,
        before=before,
        after=after,
    )


__all__ = [
    "ASSIGNMENT_REASON",
    "LEGACY_IMPORT_ACTOR",
    "OwnershipReport",
    "OwnershipSnapshot",
    "UNSCOPED_SQL",
    "assign_ownership",
]
