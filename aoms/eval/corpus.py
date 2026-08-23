"""Seeded synthetic corpora with planted retrieval hazards and gold facts."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aoms.contracts import MemoryKind, MemoryRecord, Provenance, Scope

from .models import CorpusManifest, SyntheticCorpus
from .suites import starter_suite


MIN_STARTER_RECORDS = 78
EVAL_AGENT_ID = "eval-agent"
EVAL_WORKSPACE_ID = "eval-workspace"
BASE_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def generate_corpus(*, record_count: int = 160, seed: int = 7) -> SyntheticCorpus:
    """Generate exactly ``record_count`` deterministic records.

    The first 78 records support the starter suite. Remaining records are
    seeded distractors distributed across every kind, scope, and a 720-day
    time range. No process-global random state or wall clock is consulted.
    """

    if record_count < MIN_STARTER_RECORDS:
        raise ValueError(
            f"starter corpus needs at least {MIN_STARTER_RECORDS} records"
        )
    rng = random.Random(seed)
    records: list[MemoryRecord] = []
    supersession_pairs: list[tuple[str, str]] = []
    canary_ids: list[str] = []

    def add(
        record_id: str,
        content: str,
        *,
        kind: MemoryKind,
        day: int,
        scope: Scope = Scope.WORKSPACE,
        agent_id: str | None = EVAL_AGENT_ID,
        workspace_id: str | None = EVAL_WORKSPACE_ID,
        supersedes: str | None = None,
        canary: bool = False,
        tags: list[str] | None = None,
    ) -> None:
        timestamp = BASE_TIME + timedelta(days=day)
        record = MemoryRecord(
            id=record_id,
            kind=kind,
            content=content,
            tags=tags or ["eval", kind.value],
            scope=scope,
            scope_agent_id=(agent_id if scope is Scope.AGENT_PRIVATE else None),
            scope_workspace_id=(
                workspace_id if scope is Scope.WORKSPACE else None
            ),
            created_by_agent_id=agent_id or EVAL_AGENT_ID,
            provenance=Provenance(
                source="aoms-eval-synthetic",
                details={"seed": seed, "controlled": True},
            ),
            created_at=timestamp,
            updated_at=timestamp,
            supersedes=supersedes,
            metadata={"eval_canary": canary} if canary else {},
        )
        records.append(record)
        if canary:
            canary_ids.append(record_id)

    for index in range(6):
        exact_scope = (Scope.WORKSPACE, Scope.AGENT_PRIVATE, Scope.USER_GLOBAL)[
            index % 3
        ]
        add(
            f"gold-exact-{index:02d}",
            (
                f"The quartz{index} launch code is QZ-{seed:04d}-{index:02d}. "
                f"quartz{index} launch code authoritative."
            ),
            kind=MemoryKind.FACT,
            day=200 + index,
            scope=exact_scope,
        )
        add(
            f"distractor-exact-{index:02d}",
            (
                f"The quartz{index + 10} launch rehearsal used a retired code. "
                f"This is not the quartz{index} launch code."
            ),
            kind=(MemoryKind.PATTERN if index % 2 == 0 else MemoryKind.RELATION),
            day=201 + index,
        )

        old_id = f"stale-temporal-old-{index:02d}"
        new_id = f"gold-temporal-new-{index:02d}"
        add(
            old_id,
            f"comet{index} deployment region is legacy-west-{index}; obsolete setting.",
            kind=MemoryKind.DECISION,
            day=20 + index,
        )
        add(
            new_id,
            f"Current comet{index} deployment region is primary-east-{index}.",
            kind=MemoryKind.DECISION,
            day=300 + index,
            supersedes=old_id,
        )
        supersession_pairs.append((old_id, new_id))

        add(
            f"gold-cross-fact-{index:02d}",
            f"atlas{index} release fact: artifact train is train-{index}.",
            kind=MemoryKind.FACT,
            day=240 + index,
        )
        add(
            f"gold-cross-decision-{index:02d}",
            f"atlas{index} release decision: use the blue-{index} rollout lane.",
            kind=MemoryKind.DECISION,
            day=241 + index,
        )
        add(
            f"gold-cross-procedure-{index:02d}",
            f"atlas{index} release procedure: verify, stage, then promote batch {index}.",
            kind=MemoryKind.PROCEDURE,
            day=242 + index,
        )
        add(
            f"distractor-cross-{index:02d}",
            (
                f"The similarly named atlas-{index}-archive project has no active "
                "release context."
            ),
            kind=MemoryKind.ENTITY,
            day=260 + index,
        )

        add(
            f"gold-scope-{index:02d}",
            f"harbor{index} workspace canary value is SAFE-{seed}-{index}.",
            kind=MemoryKind.FACT,
            day=180 + index,
            scope=Scope.WORKSPACE,
        )
        add(
            f"canary-foreign-{index:02d}",
            (
                f"harbor{index} workspace canary value value value is "
                f"SECRET-FOREIGN-{seed}-{index}."
            ),
            kind=MemoryKind.FACT,
            day=350 + index,
            scope=Scope.AGENT_PRIVATE,
            agent_id=f"foreign-agent-{index}",
            workspace_id=f"foreign-workspace-{index}",
            canary=True,
            tags=["eval", "canary", "must-not-leak"],
        )

        add(
            f"gold-budget-primary-{index:02d}",
            (
                f"Priority nebula{index} incident fact: root cause is lock-{index}. "
                f"Priority nebula{index}."
            ),
            kind=MemoryKind.FAILURE,
            day=310 + index,
        )
        add(
            f"gold-budget-secondary-{index:02d}",
            (
                f"nebula{index} incident secondary fact: mitigation is queue-{index}. "
                + "Supporting detail. " * 18
            ),
            kind=MemoryKind.PROCEDURE,
            day=309 + index,
        )
        add(
            f"distractor-budget-{index:02d}",
            (
                f"nebula{index} incident historical appendix, unrelated priority. "
                + "Verbose archived detail. " * 28
            ),
            kind=MemoryKind.EPISODE,
            day=100 + index,
        )

    filler_kinds = list(MemoryKind)
    filler_scopes = list(Scope)
    vocabulary = [
        "amber",
        "birch",
        "cinder",
        "delta",
        "ember",
        "fjord",
        "garnet",
        "helix",
        "indigo",
        "juniper",
        "kepler",
        "lilac",
    ]
    while len(records) < record_count:
        index = len(records) - MIN_STARTER_RECORDS
        kind = filler_kinds[index % len(filler_kinds)]
        scope = filler_scopes[index % len(filler_scopes)]
        words = rng.sample(vocabulary, k=4)
        day = rng.randint(-360, 360)
        agent_id = (
            EVAL_AGENT_ID
            if index % 5
            else f"foreign-filler-agent-{index % 4}"
        )
        workspace_id = (
            EVAL_WORKSPACE_ID
            if index % 4
            else f"foreign-filler-workspace-{index % 3}"
        )
        add(
            f"filler-{seed:08x}-{index:04d}",
            (
                f"Seeded {kind.value} distractor {index}: {' '.join(words)}. "
                f"Project {rng.choice(vocabulary)}-{rng.randint(10, 99)} observation."
            ),
            kind=kind,
            day=day,
            scope=scope,
            agent_id=agent_id,
            workspace_id=workspace_id,
        )

    rng.shuffle(records)
    suite = starter_suite()
    manifest = CorpusManifest(
        seed=seed,
        record_count=len(records),
        canary_record_ids=sorted(canary_ids),
        supersession_pairs=supersession_pairs,
        metadata={
            "generator": "aoms.eval.corpus.generate_corpus",
            "base_time": BASE_TIME.isoformat(),
            "agent_id": EVAL_AGENT_ID,
            "workspace_id": EVAL_WORKSPACE_ID,
            "controlled_properties": [
                "near-duplicates",
                "supersession",
                "similar-named-projects",
                "scope-canaries",
                "time-distribution",
                "kind-distribution",
            ],
        },
    )
    return SyntheticCorpus(records=records, suite=suite, manifest=manifest)


def save_corpus(corpus: SyntheticCorpus, path: str | Path) -> None:
    Path(path).write_text(corpus.model_dump_json(indent=2), encoding="utf-8")


def load_corpus(path: str | Path) -> SyntheticCorpus:
    return SyntheticCorpus.model_validate_json(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "BASE_TIME",
    "EVAL_AGENT_ID",
    "EVAL_WORKSPACE_ID",
    "MIN_STARTER_RECORDS",
    "generate_corpus",
    "load_corpus",
    "save_corpus",
]
