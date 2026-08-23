from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallRequest,
    Scope,
    ScopeContext,
)
from aoms.embeddings import NullProvider
from aoms.recall import RecallEngine
from aoms.repositories import SQLiteMemoryRepository
from demo.relay_fixture.seed import RELAY_WORKSPACE, load_scenario, seed_store
from demo.relay_fixture.verify import verify_run

REFERENCE_SERVICE = '''\
from __future__ import annotations
import json
import sqlite3
from copy import deepcopy
from pathlib import Path

def _redact(value):
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if key.endswith("_token") else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value

class RelayStore:
    def __init__(self, path):
        self.path = Path(path)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL)")

    def accept(self, headers, payload, received_at):
        event_id = headers.get("X-Relay-Event")
        if not event_id:
            raise ValueError("X-Relay-Event is required")
        serialized = json.dumps(_redact(deepcopy(dict(payload))), sort_keys=True)
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("INSERT OR IGNORE INTO events(event_id, received_at, payload) VALUES (?, ?, ?)", (event_id, received_at, serialized))
            accepted = cursor.rowcount == 1
        return {"status": "accepted" if accepted else "duplicate", "event_id": event_id}

    def list_events(self):
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT event_id, received_at, payload FROM events ORDER BY seq").fetchall()
        return [{"event_id": event_id, "received_at": received_at, "payload": json.loads(payload)} for event_id, received_at, payload in rows]
'''


def _app(repository: SQLiteMemoryRepository, agent_id: str) -> AOMSApplication:
    return AOMSApplication(
        repository,
        scope_context=ScopeContext(agent_id=agent_id, workspace_id=RELAY_WORKSPACE),
        embedding_provider=NullProvider(),
        background_embeddings=False,
    )


def _workspace_record(
    memory_id: str,
    content: str,
    *,
    kind: MemoryKind,
    timestamp: datetime,
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        kind=kind,
        content=content,
        scope=Scope.WORKSPACE,
        scope_workspace_id=RELAY_WORKSPACE,
        created_by_agent_id="relay-planner",
        provenance=Provenance(source="relay-ranking-regression"),
        created_at=timestamp,
        updated_at=timestamp,
    )


async def _write_stage_artifact(
    root: Path,
    relative_path: str,
    app: AOMSApplication,
    *,
    query: str,
    token_budget: int,
) -> None:
    recalled = await app.recall(RecallRequest(task=query, token_budget=token_budget))
    receipt = (await app.recent_recall_receipts(limit=1))[0]
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"receipt": receipt.model_dump(mode="json"), "context": recalled.context},
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_relay_seeder_and_verifier_round_trip(tmp_path: Path) -> None:
    scenario = load_scenario()
    db_path = tmp_path / "fixture-aoms.sqlite3"
    seeded = await seed_store(db_path)
    expected_ids = {
        *(item["memory_id"] for item in scenario["constraints"]),
        scenario["tempting_wrong_approach"]["memory_id"],
        scenario["regression_clue"]["memory_id"],
        *(item["memory_id"] for item in scenario["canaries"]),
    }
    assert set(seeded.memory_ids) == expected_ids

    repository = SQLiteMemoryRepository(db_path)
    run_dir = tmp_path / "completed-run"
    implementer = scenario["stages"]["implementer"]
    reviewer = scenario["stages"]["reviewer"]
    await _write_stage_artifact(
        run_dir,
        scenario["artifacts"]["stage_2_recall"],
        _app(repository, implementer["agent_id"]),
        query=implementer["recall_query"],
        token_budget=implementer["token_ceiling"],
    )
    await _write_stage_artifact(
        run_dir,
        scenario["artifacts"]["stage_3_recall"],
        _app(repository, reviewer["agent_id"]),
        query=reviewer["recall_query"],
        token_budget=reviewer["token_ceiling"],
    )

    fixture_repository = Path(__file__).parents[2] / "demo" / "relay_fixture" / "repository"
    completed_repository = run_dir / scenario["artifacts"]["completed_repository"]
    shutil.copytree(fixture_repository, completed_repository)
    (completed_repository / "relay_service" / "service.py").write_text(
        REFERENCE_SERVICE, encoding="utf-8"
    )

    report = verify_run(run_dir)

    assert report.passed, report.failures
    assert report.failures == ()
    assert "stage-2 selected all injected constraints" in report.checks
    assert "stage-3 selected the private regression clue" in report.checks
    assert "acceptance: durable idempotency" in report.checks


@pytest.mark.asyncio
async def test_implementer_query_keeps_constraints_ahead_of_delayed_handoff(
    tmp_path: Path,
) -> None:
    """The proof must not depend on how quickly the planner subprocess runs."""

    scenario = load_scenario()
    script_path = Path(__file__).parents[2] / "demo" / "relay_fixture" / "scripted.yaml"
    script = yaml.safe_load(script_path.read_text(encoding="utf-8"))
    planner_calls = script["stages"]["planner"]["calls"]
    implementer_calls = script["stages"]["implementer"]["calls"]
    handoff = next(call for call in planner_calls if call.get("name") == "remember")
    recall = next(call for call in implementer_calls if call.get("name") == "recall")
    assert recall["arguments"]["task"] == scenario["stages"]["implementer"][
        "recall_query"
    ]

    seeded_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    handoff_at = seeded_at + timedelta(hours=1)
    records = [
        *(
            _workspace_record(
                item["memory_id"],
                item["text"],
                kind=MemoryKind.FACT,
                timestamp=seeded_at,
            )
            for item in scenario["constraints"]
        ),
        _workspace_record(
            scenario["tempting_wrong_approach"]["memory_id"],
            scenario["tempting_wrong_approach"]["text"],
            kind=MemoryKind.DECISION,
            timestamp=seeded_at,
        ),
        _workspace_record(
            handoff["arguments"]["id"],
            handoff["arguments"]["content"],
            kind=MemoryKind(handoff["arguments"]["kind"]),
            timestamp=handoff_at,
        ),
    ]
    repository = SQLiteMemoryRepository(tmp_path / "ranking.sqlite3")
    await repository.store_many(records)
    context = ScopeContext(
        agent_id=scenario["stages"]["implementer"]["agent_id"],
        workspace_id=RELAY_WORKSPACE,
    )
    engine = RecallEngine(
        repository,
        embedding_provider=NullProvider(),
        scope_context=context,
        clock=lambda: handoff_at + timedelta(minutes=1),
    )

    result = await engine.recall(RecallRequest(**recall["arguments"]))

    selected_ids = {source.memory_id for source in result.sources}
    constraint_ids = {item["memory_id"] for item in scenario["constraints"]}
    assert constraint_ids <= selected_ids


def test_constraints_are_not_present_in_the_tiny_repository() -> None:
    scenario = load_scenario()
    fixture_repository = Path(__file__).parents[2] / "demo" / "relay_fixture" / "repository"
    repository_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in fixture_repository.rglob("*")
        if path.is_file() and path.suffix in {".py", ".md", ".toml"}
    )

    for constraint in scenario["constraints"]:
        assert constraint["text"] not in repository_text
        assert constraint["memory_id"] not in repository_text
    for canary in scenario["canaries"]:
        assert canary["text"] not in repository_text
