from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallRequest,
    Scope,
    ScopeContext,
    SearchRequest,
)
from aoms.embeddings import NullProvider
from aoms.repositories import SQLiteMemoryRepository
from aoms.repositories.sqlite import LATEST_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CORPUS = ROOT / "tests" / "v2" / "fixtures" / "corpus"


def run_cli(
    *arguments: str,
    data_dir: Path,
    check: bool = False,
    input_text: str | None = None,
    environ_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environ = dict(os.environ)
    environ.update(
        {
            "AOMS_DATA_DIR": str(data_dir),
            "AOMS_EMBEDDING_PROVIDER": "none",
            "PYTHONPATH": str(ROOT),
        }
    )
    environ.update(environ_overrides or {})
    return subprocess.run(
        [sys.executable, "-m", "aoms.cli", *arguments],
        cwd=ROOT,
        env=environ,
        text=True,
        input=input_text,
        capture_output=True,
        check=check,
    )


def test_cli_help_and_init_first_run_copy(tmp_path: Path) -> None:
    help_result = run_cli("--help", data_dir=tmp_path / "unused", check=True)
    assert "Local-first shared memory for MCP agent fleets." in help_result.stdout
    for command in (
        "init",
        "setup",
        "tour",
        "recall",
        "remember",
        "doctor",
        "assign-ownership",
        "import",
        "backfill",
        "sweep",
        "export",
        "restore",
        "token",
        "mcp",
    ):
        assert command in help_result.stdout

    data_dir = tmp_path / "data"
    result = run_cli("init", data_dir=data_dir, check=True)

    assert (data_dir / "aoms.sqlite3").is_file()
    assert f"SQLite store ready (schema {LATEST_SCHEMA_VERSION})" in result.stdout
    assert "cortex-mem setup claude" in result.stdout
    assert "cortex-mem setup codex" in result.stdout
    assert "cortex-mem setup openclaw" in result.stdout


def test_cli_import_export_restore_smoke(tmp_path: Path) -> None:
    source_data = tmp_path / "source-data"
    restored_data = tmp_path / "restored-data"
    bundle = tmp_path / "portable-export"

    run_cli("init", data_dir=source_data, check=True)
    imported = run_cli("import", str(FIXTURE_CORPUS), data_dir=source_data, check=True)
    backfilled = run_cli("backfill", data_dir=source_data, check=True)
    swept = run_cli("sweep", data_dir=source_data, check=True)
    exported = run_cli("export", str(bundle), data_dir=source_data, check=True)
    restored = run_cli("restore", str(bundle), data_dir=restored_data, check=True)

    assert "Imported 5/5 record(s)" in imported.stdout
    assert "Backfill finished" in backfilled.stdout
    assert "Sweep finished" in swept.stdout
    assert "Exported 5 record(s)" in exported.stdout
    assert "Restored 5 record(s)" in restored.stdout
    with sqlite3.connect(restored_data / "aoms.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 5
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM memories "
                "WHERE scope_workspace_id = ? AND created_by_agent_id = 'cli'",
                (str(ROOT.resolve()),),
            ).fetchone()[0]
            == 5
        )


def test_token_cli_create_list_and_revoke_without_reprinting_secret(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "tokens"
    run_cli("init", data_dir=data_dir, check=True)
    created = run_cli(
        "token",
        "create",
        "remote-agent",
        "--scope",
        "read",
        "--scope",
        "write",
        "--agent-id",
        "agent-7",
        "--workspace-id",
        "workspace-9",
        data_dir=data_dir,
        check=True,
    )
    secret = created.stdout.strip().splitlines()[-1]
    token_id = secret.split("_", 2)[1]
    assert secret.startswith("aoms_")
    assert "shown once" in created.stdout

    listed = run_cli("token", "list", data_dir=data_dir, check=True)
    assert token_id in listed.stdout
    assert "read,write" in listed.stdout
    assert "agent-7 / workspace-9" in listed.stdout
    assert secret not in listed.stdout

    revoked = run_cli("token", "revoke", token_id, data_dir=data_dir, check=True)
    assert f"Revoked token {token_id}" in revoked.stdout
    relisted = run_cli("token", "list", data_dir=data_dir, check=True)
    assert "revoked" in relisted.stdout


def test_doctor_missing_corrupt_and_empty_store_findings(tmp_path: Path) -> None:
    missing = run_cli("doctor", data_dir=tmp_path / "missing")
    assert missing.returncode == 1
    assert "[FAIL] Data directory" in missing.stdout
    assert "cortex-mem init --data-dir" in missing.stdout

    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    (corrupt_dir / "aoms.sqlite3").write_bytes(b"this is not a sqlite database")
    corrupt = run_cli("doctor", data_dir=corrupt_dir)
    assert corrupt.returncode == 1
    assert "[FAIL] SQLite store" in corrupt.stdout
    assert "Restore a verified export" in corrupt.stdout

    empty_dir = tmp_path / "empty"
    run_cli("init", data_dir=empty_dir, check=True)
    empty = run_cli("doctor", data_dir=empty_dir)
    assert empty.returncode == 0
    assert "[WARN] Memory records: store is healthy but empty" in empty.stdout
    assert "[PASS] Receipt store" in empty.stdout
    assert "Doctor finished: 0 failure(s)" in empty.stdout


def _seed_ownership_fixture(data_dir: Path) -> None:
    run_cli("init", data_dir=data_dir, check=True)
    timestamp = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    records = [
        MemoryRecord(
            id="legacy-fact",
            kind=MemoryKind.FACT,
            content="heritagequartz fleet history",
            scope=Scope.WORKSPACE,
            provenance=Provenance(source="legacy.jsonl", tier="semantic"),
            created_at=timestamp,
            updated_at=timestamp,
        ),
        MemoryRecord(
            id="legacy-decision",
            kind=MemoryKind.DECISION,
            content="heritagequartz migration decision",
            scope=Scope.AGENT_PRIVATE,
            created_by_agent_id="known-importer",
            provenance=Provenance(source="legacy.jsonl", tier="episodic"),
            created_at=timestamp,
            updated_at=timestamp,
        ),
        MemoryRecord(
            id="already-scoped",
            kind=MemoryKind.PROCEDURE,
            content="unrelated scoped procedure",
            scope=Scope.WORKSPACE,
            scope_workspace_id="fixture-workspace",
            created_by_agent_id="fixture-agent",
            provenance=Provenance(source="current"),
            created_at=timestamp,
            updated_at=timestamp,
        ),
    ]
    asyncio.run(
        SQLiteMemoryRepository(data_dir / "aoms.sqlite3").store_many(records)
    )


def _ownership_result(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.stdout.splitlines()[-2] == "JSON report:"
    return json.loads(result.stdout.splitlines()[-1])


def test_assign_ownership_help_limits_bulk_scope(tmp_path: Path) -> None:
    result = run_cli(
        "assign-ownership", "--help", data_dir=tmp_path / "unused", check=True
    )

    assert "--scope [user-global]" in result.stdout
    assert "--dry-run / --execute" in result.stdout
    assert "[default: dry-run]" in result.stdout
    assert "restrictive scopes would fabricate" in result.stdout
    assert "--batch-size INTEGER" in result.stdout
    assert "--data-dir DIRECTORY" in result.stdout


def test_assign_ownership_dry_run_does_not_change_records(tmp_path: Path) -> None:
    data_dir = tmp_path / "ownership-dry-run"
    _seed_ownership_fixture(data_dir)

    result = run_cli(
        "assign-ownership",
        "--scope",
        "user-global",
        "--batch-size",
        "1",
        data_dir=data_dir,
        check=True,
    )
    payload = _ownership_result(result)

    assert "Ownership assignment (DRY RUN)" in result.stdout
    assert payload["dry_run"] is True
    assert payload["would_assign"] == 2
    assert payload["assigned_records"] == 0
    assert payload["remaining_unscoped"] == 2
    assert payload["before"]["by_kind"] == {"decision": 1, "fact": 1}
    assert payload["before"]["by_tier"] == {"episodic": 1, "semantic": 1}
    assert payload["after"] == payload["before"]
    with sqlite3.connect(data_dir / "aoms.sqlite3") as connection:
        rows = connection.execute(
            "SELECT id, scope, created_by_agent_id, record_json FROM memories "
            "ORDER BY id"
        ).fetchall()
    by_id = {row[0]: row for row in rows}
    assert by_id["legacy-fact"][1:3] == ("workspace", None)
    assert "ownership_assignment" not in by_id["legacy-fact"][3]
    assert by_id["already-scoped"][1:3] == ("workspace", "fixture-agent")


def test_assign_ownership_execute_is_exact_idempotent_and_restores_visibility(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "ownership-execute"
    _seed_ownership_fixture(data_dir)
    repository = SQLiteMemoryRepository(data_dir / "aoms.sqlite3")
    context = ScopeContext(
        agent_id="fixture-reader", workspace_id="fixture-workspace"
    )

    async def visible_ids() -> tuple[set[str], set[str]]:
        application = AOMSApplication(
            repository,
            scope_context=context,
            embedding_provider=NullProvider(),
        )
        search = await application.search(SearchRequest(query="heritagequartz"))
        recall = await application.recall(
            RecallRequest(task="heritagequartz", token_budget=1_000)
        )
        return (
            {item.record.id for item in search.items},
            {source.memory_id for source in recall.sources},
        )

    search_ids_before, recall_ids_before = asyncio.run(visible_ids())
    assert search_ids_before == set()
    assert {"legacy-decision", "legacy-fact"}.isdisjoint(recall_ids_before)
    executed = run_cli(
        "assign-ownership",
        "--scope",
        "user-global",
        "--execute",
        "--batch-size",
        "1",
        data_dir=data_dir,
        check=True,
    )
    payload = _ownership_result(executed)

    assert payload["assigned_records"] == 2
    assert payload["remaining_unscoped"] == 0
    assert payload["after"] == {
        "by_kind": {},
        "by_tier": {},
        "unscoped_records": 0,
    }
    search_ids, recall_ids = asyncio.run(visible_ids())
    assert search_ids == {"legacy-decision", "legacy-fact"}
    assert {"legacy-decision", "legacy-fact"}.issubset(recall_ids)

    fact = asyncio.run(repository.get("legacy-fact"))
    decision = asyncio.run(repository.get("legacy-decision"))
    scoped = asyncio.run(repository.get("already-scoped"))
    assert fact is not None and decision is not None and scoped is not None
    for record in (fact, decision):
        assert record.scope is Scope.USER_GLOBAL
        assert record.scope_agent_id is None
        assert record.scope_workspace_id is None
        annotation = record.provenance.details["ownership_assignment"]
        assert annotation["assignment_timestamp"] == payload[
            "assignment_timestamp"
        ]
        assert annotation["tool_version"] == payload["tool_version"]
        assert annotation["reason"] == (
            "legacy-import bulk assignment 2026-08-23"
        )
    assert fact.created_by_agent_id == "legacy-import"
    assert decision.created_by_agent_id == "known-importer"
    assert "ownership_assignment" not in scoped.provenance.details

    repeated = run_cli(
        "assign-ownership",
        "--scope",
        "user-global",
        "--execute",
        data_dir=data_dir,
        check=True,
    )
    repeated_payload = _ownership_result(repeated)
    assert repeated_payload["would_assign"] == 0
    assert repeated_payload["assigned_records"] == 0
    assert repeated_payload["remaining_unscoped"] == 0
    assert asyncio.run(repository.get("legacy-fact")) == fact


def test_doctor_unscoped_finding_references_assignment_command(tmp_path: Path) -> None:
    data_dir = tmp_path / "doctor-unscoped"
    _seed_ownership_fixture(data_dir)

    result = run_cli("doctor", data_dir=data_dir, check=True)

    assert "[WARN] Unscoped records: 2 record(s) are excluded" in result.stdout
    assert (
        "Action: Run: cortex-mem assign-ownership --scope user-global --execute"
        in result.stdout
    )


def test_cli_recall_remember_round_trip_and_idempotency(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    binding = {
        "AOMS_AGENT_ID": "cli-test-agent",
        "AOMS_WORKSPACE": "cli-test-workspace",
    }
    run_cli("init", data_dir=data_dir, check=True)

    created = run_cli(
        "remember",
        "--content",
        "-",
        "--kind",
        "decision",
        "--tags",
        "release,marmalade",
        "--idempotency-key",
        "release-channel",
        data_dir=data_dir,
        input_text="Decision: deploy marmalade through the amber channel.",
        environ_overrides=binding,
        check=True,
    )
    updated = run_cli(
        "remember",
        "--content",
        "Decision: deploy marmalade through the green channel.",
        "--kind",
        "decision",
        "--tags",
        "release",
        "--idempotency-key",
        "release-channel",
        data_dir=data_dir,
        environ_overrides=binding,
        check=True,
    )
    recalled = run_cli(
        "recall",
        "--task",
        "Which marmalade deployment channel should be used?",
        "--budget",
        "300",
        "--format",
        "json",
        data_dir=data_dir,
        environ_overrides=binding,
        check=True,
    )

    payload = json.loads(recalled.stdout)
    assert created.stdout.startswith("Created memory cli-")
    assert updated.stdout.startswith("Updated memory cli-")
    assert "green channel" in payload["context"]
    assert "amber channel" not in payload["context"]
    assert payload["sources"][0]["kind"] == "decision"
    with sqlite3.connect(data_dir / "aoms.sqlite3") as connection:
        row = connection.execute(
            "SELECT scope_workspace_id, created_by_agent_id, COUNT(*) FROM memories"
        ).fetchone()
    assert row == ("cli-test-workspace", "cli-test-agent", 1)


def test_cli_empty_recall_is_actionable(tmp_path: Path) -> None:
    data_dir = tmp_path / "empty"
    run_cli("init", data_dir=data_dir, check=True)

    recalled = run_cli(
        "recall", "--task", "first empty recall", data_dir=data_dir, check=True
    )

    assert recalled.stdout.strip() == (
        "Store is empty for your scopes. Next: cortex-mem remember / import / tour."
    )


def test_tour_is_disposable_and_never_touches_canonical_store(tmp_path: Path) -> None:
    data_dir = tmp_path / "canonical"
    run_cli("init", data_dir=data_dir, check=True)
    run_cli(
        "remember",
        "--content",
        "Canonical sentinel must remain untouched.",
        data_dir=data_dir,
        check=True,
    )
    with sqlite3.connect(data_dir / "aoms.sqlite3") as connection:
        before = connection.execute(
            "SELECT COUNT(*), MIN(record_json) FROM memories"
        ).fetchone()
        receipts_before = connection.execute(
            "SELECT COUNT(*) FROM recall_receipts"
        ).fetchone()[0]

    toured = run_cli("tour", data_dir=data_dir, check=True)

    assert "DISPOSABLE DEMO store:" in toured.stdout
    assert "Seeded 3 demo memories" in toured.stdout
    assert "scope_filtered=1 superseded=1" in toured.stdout
    assert "Auto-cleaned disposable demo store:" in toured.stdout
    with sqlite3.connect(data_dir / "aoms.sqlite3") as connection:
        after = connection.execute(
            "SELECT COUNT(*), MIN(record_json) FROM memories"
        ).fetchone()
        receipts_after = connection.execute(
            "SELECT COUNT(*) FROM recall_receipts"
        ).fetchone()[0]
    assert after == before
    assert receipts_after == receipts_before
