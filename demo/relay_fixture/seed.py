"""Seed the relay's runtime-only facts into an isolated AOMS SQLite store."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    Provenance,
    RememberRequest,
    Scope,
    ScopeContext,
)
from aoms.embeddings import NullProvider
from aoms.repositories import SQLiteMemoryRepository

SCENARIO_PATH = Path(__file__).with_name("scenario.yaml")
RELAY_WORKSPACE = "relay-gauntlet"


@dataclass(frozen=True, slots=True)
class SeedResult:
    db_path: Path
    memory_ids: tuple[str, ...]


def load_scenario(path: Path = SCENARIO_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _application(
    repository: SQLiteMemoryRepository, *, agent_id: str, workspace_id: str
) -> AOMSApplication:
    return AOMSApplication(
        repository,
        scope_context=ScopeContext(agent_id=agent_id, workspace_id=workspace_id),
        embedding_provider=NullProvider(),
        background_embeddings=False,
    )


async def _remember(
    app: AOMSApplication,
    *,
    memory_id: str,
    text: str,
    kind: MemoryKind,
    scope: Scope,
    scenario_id: str,
) -> None:
    await app.remember(
        RememberRequest(
            id=memory_id,
            kind=kind,
            content=text,
            tags=["relay", "launch-demo", scenario_id],
            scope=scope,
            provenance=Provenance(
                source="demo/relay_fixture/scenario.yaml",
                record_type="runtime-injected",
                details={"scenario_id": scenario_id},
            ),
        )
    )


async def seed_store(
    db_path: str | Path, *, scenario_path: Path = SCENARIO_PATH
) -> SeedResult:
    """Create fixture memories through the public application boundary."""

    target = Path(db_path)
    scenario = load_scenario(scenario_path)
    repository = SQLiteMemoryRepository(target)
    planner_id = scenario["stages"]["planner"]["agent_id"]
    planner = _application(
        repository, agent_id=planner_id, workspace_id=RELAY_WORKSPACE
    )
    memory_ids: list[str] = []

    for constraint in scenario["constraints"]:
        await _remember(
            planner,
            memory_id=constraint["memory_id"],
            text=constraint["text"],
            kind=MemoryKind.FACT,
            scope=Scope.WORKSPACE,
            scenario_id=scenario["id"],
        )
        memory_ids.append(constraint["memory_id"])

    decision = scenario["tempting_wrong_approach"]
    await _remember(
        planner,
        memory_id=decision["memory_id"],
        text=decision["text"],
        kind=MemoryKind.DECISION,
        scope=Scope.WORKSPACE,
        scenario_id=scenario["id"],
    )
    memory_ids.append(decision["memory_id"])

    reviewer = _application(
        repository,
        agent_id=scenario["stages"]["reviewer"]["agent_id"],
        workspace_id=RELAY_WORKSPACE,
    )
    clue = scenario["regression_clue"]
    await _remember(
        reviewer,
        memory_id=clue["memory_id"],
        text=clue["text"],
        kind=MemoryKind.FAILURE,
        scope=Scope.AGENT_PRIVATE,
        scenario_id=scenario["id"],
    )
    memory_ids.append(clue["memory_id"])

    for canary in scenario["canaries"]:
        owner = _application(
            repository,
            agent_id=canary["owner_agent_id"],
            workspace_id=canary["workspace_id"],
        )
        await _remember(
            owner,
            memory_id=canary["memory_id"],
            text=canary["text"],
            kind=MemoryKind.FACT,
            scope=Scope(canary["scope"]),
            scenario_id=scenario["id"],
        )
        memory_ids.append(canary["memory_id"])

    return SeedResult(db_path=target, memory_ids=tuple(memory_ids))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()
    result = asyncio.run(seed_store(args.db))
    print(f"seeded {len(result.memory_ids)} memories into {result.db_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
