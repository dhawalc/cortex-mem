from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CORPUS = ROOT / "tests" / "v2" / "fixtures" / "corpus"


def run_cli(
    *arguments: str,
    data_dir: Path,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    environ = dict(os.environ)
    environ.update(
        {
            "AOMS_DATA_DIR": str(data_dir),
            "AOMS_EMBEDDING_PROVIDER": "none",
            "PYTHONPATH": str(ROOT),
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "aoms.cli", *arguments],
        cwd=ROOT,
        env=environ,
        text=True,
        capture_output=True,
        check=check,
    )


def test_cli_help_and_init_first_run_copy(tmp_path: Path) -> None:
    help_result = run_cli("--help", data_dir=tmp_path / "unused", check=True)
    assert "Local-first shared memory for MCP agent fleets." in help_result.stdout
    for command in (
        "init",
        "doctor",
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
    assert "SQLite store ready (schema 5)" in result.stdout
    assert "claude mcp add aoms -- uvx cortex-mem mcp" in result.stdout
    assert (
        "openclaw config set mcp.servers.aoms "
        '\'{"command":"uvx","args":["cortex-mem","mcp"]}\' --strict-json'
        in result.stdout
    )


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
                "WHERE scope_workspace_id = 'default' "
                "AND created_by_agent_id = 'default'"
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
