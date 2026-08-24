"""Deterministic, read-only supersession diagnostics and timeline reconstruction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from aoms.contracts import MemoryRecord, Scope


CYCLE = "cycle"
DANGLING_TARGET = "dangling-target"
MULTIPLE_HEADS = "multiple-heads"
BOTH_ENDS_RETRIEVABLE = "both-ends-retrievable"
SCOPE_BOUNDARY = "scope-boundary"


@dataclass(frozen=True, slots=True)
class ChainFinding:
    """One structural fact; it is never a semantic truth judgment."""

    category: str
    record_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class ChainHealthReport:
    records_scanned: int
    findings: tuple[ChainFinding, ...]

    def count(self, category: str) -> int:
        return sum(item.category == category for item in self.findings)


@dataclass(frozen=True, slots=True)
class TimelineVersion:
    record: MemoryRecord
    valid_from: datetime
    valid_until: datetime | None
    successor_ids: tuple[str, ...]
    active_at_boundary: bool


@dataclass(frozen=True, slots=True)
class ChainTimeline:
    anchor_id: str
    versions: tuple[TimelineVersion, ...]
    as_of: datetime | None = None
    reconstruction_note: str = (
        "Declared-lineage reconstruction from retained created_at and supersedes "
        "evidence; not omniscient event history."
    )


def _scope_key(record: MemoryRecord) -> tuple[str, str | None]:
    if record.scope is Scope.USER_GLOBAL:
        return (record.scope.value, None)
    if record.scope is Scope.WORKSPACE:
        return (record.scope.value, record.scope_workspace_id)
    return (record.scope.value, record.scope_agent_id)


def _visibility_domains_overlap(left: MemoryRecord, right: MemoryRecord) -> bool:
    if Scope.USER_GLOBAL in {left.scope, right.scope}:
        return True
    if left.scope is right.scope is Scope.WORKSPACE:
        return left.scope_workspace_id == right.scope_workspace_id
    if left.scope is right.scope is Scope.AGENT_PRIVATE:
        return left.scope_agent_id == right.scope_agent_id
    # An agent-private and a workspace record can be visible together to a
    # context matching both independent bindings.
    return True


def diagnose_chains(
    records: Iterable[MemoryRecord], *, fts_memory_ids: set[str] | None = None
) -> ChainHealthReport:
    """Inspect only declared links; content is never interpreted or changed."""

    materialized = list(records)
    by_id = {record.id: record for record in materialized}
    findings: list[ChainFinding] = []

    for record in sorted(materialized, key=lambda item: item.id):
        target_id = record.supersedes
        if not target_id:
            continue
        target = by_id.get(target_id)
        if target is None:
            findings.append(
                ChainFinding(
                    DANGLING_TARGET,
                    (record.id, target_id),
                    f"{record.id} declares missing predecessor {target_id}",
                )
            )
            continue
        if _scope_key(record) != _scope_key(target):
            findings.append(
                ChainFinding(
                    SCOPE_BOUNDARY,
                    (target.id, record.id),
                    "declared link crosses different scope/binding predicates",
                )
            )
        if (
            fts_memory_ids is not None
            and record.id in fts_memory_ids
            and target.id in fts_memory_ids
            and _visibility_domains_overlap(record, target)
        ):
            findings.append(
                ChainFinding(
                    BOTH_ENDS_RETRIEVABLE,
                    (target.id, record.id),
                    "both declared-link endpoints are FTS-retrievable in at least "
                    "one shared scope context",
                )
            )

    cycle_keys: set[tuple[str, ...]] = set()
    completed: set[str] = set()
    for start in sorted(by_id):
        if start in completed:
            continue
        path: list[str] = []
        positions: dict[str, int] = {}
        current: str | None = start
        while current in by_id and current not in completed:
            if current in positions:
                cycle = path[positions[current] :]
                # A sorted key makes one deterministic finding independent of
                # which node first entered the functional graph.
                cycle_keys.add(tuple(sorted(cycle)))
                break
            positions[current] = len(path)
            path.append(current)
            current = by_id[current].supersedes
        completed.update(path)
    for cycle in sorted(cycle_keys):
        findings.append(
            ChainFinding(CYCLE, cycle, "declared supersedes links form a cycle")
        )

    adjacency = {record_id: set() for record_id in by_id}
    successor_ids = {record_id: set() for record_id in by_id}
    for record in materialized:
        if record.supersedes in by_id:
            adjacency[record.id].add(record.supersedes)
            adjacency[record.supersedes].add(record.id)
            successor_ids[record.supersedes].add(record.id)
    visited: set[str] = set()
    for start in sorted(by_id):
        if start in visited:
            continue
        component: set[str] = set()
        pending = [start]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(adjacency[current] - component)
        visited.update(component)
        if len(component) < 2:
            continue
        heads = tuple(sorted(node for node in component if not successor_ids[node]))
        if len(heads) > 1:
            findings.append(
                ChainFinding(
                    MULTIPLE_HEADS,
                    heads,
                    "one connected declared lineage has multiple apparent heads",
                )
            )

    findings.sort(key=lambda item: (item.category, item.record_ids, item.detail))
    return ChainHealthReport(len(materialized), tuple(findings))


def reconstruct_timeline(
    anchor_id: str,
    records: Iterable[MemoryRecord],
    *,
    as_of: datetime | None = None,
) -> ChainTimeline:
    """Infer validity windows from visible, retained successor timestamps only."""

    materialized = sorted(records, key=lambda item: (item.created_at, item.id))
    by_id = {record.id: record for record in materialized}
    successors: dict[str, list[MemoryRecord]] = {record.id: [] for record in materialized}
    for record in materialized:
        if record.supersedes in by_id:
            successors[record.supersedes].append(record)
    versions: list[TimelineVersion] = []
    for record in materialized:
        direct = sorted(successors[record.id], key=lambda item: (item.created_at, item.id))
        valid_until = direct[0].created_at if direct else None
        active = valid_until is None
        if as_of is not None:
            active = record.created_at <= as_of and (
                valid_until is None or as_of < valid_until
            )
        versions.append(
            TimelineVersion(
                record=record,
                valid_from=record.created_at,
                valid_until=valid_until,
                successor_ids=tuple(item.id for item in direct),
                active_at_boundary=active,
            )
        )
    return ChainTimeline(anchor_id, tuple(versions), as_of=as_of)


__all__ = [
    "BOTH_ENDS_RETRIEVABLE",
    "CYCLE",
    "DANGLING_TARGET",
    "MULTIPLE_HEADS",
    "SCOPE_BOUNDARY",
    "ChainFinding",
    "ChainHealthReport",
    "ChainTimeline",
    "TimelineVersion",
    "diagnose_chains",
    "reconstruct_timeline",
]
