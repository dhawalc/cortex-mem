from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from aoms.cli import main
from aoms.contracts import MemoryKind, Scope
from aoms.importers import (
    ClaudeMemAdapter,
    ClaudeMemSchemaError,
    ImportContext,
    MarkdownObsidianAdapter,
    SourceAdapter,
    run_import,
)
from aoms.repositories import SQLiteMemoryRepository


FIXTURES = Path(__file__).parent / "fixtures" / "importers"
IMPORTED_AT = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _context(
    scope: Scope = Scope.WORKSPACE, workspace_id: str | None = "fixture-workspace"
) -> ImportContext:
    return ImportContext(
        scope=scope,
        imported_at=IMPORTED_AT,
        actor_id="fixture-importer",
        workspace_id=workspace_id,
    )


def _claude_mem_database(tmp_path: Path) -> Path:
    database = tmp_path / "claude-mem.db"
    schema = (FIXTURES / "claude_mem" / "schema_v49.sql").read_text()
    with sqlite3.connect(database) as connection:
        connection.executescript(schema)
    return database


def test_markdown_preview_is_read_only_and_provenance_complete(tmp_path: Path) -> None:
    source = FIXTURES / "markdown" / "vault"
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in source.glob("*.md")
    }
    target = tmp_path / "does-not-exist" / "aoms.sqlite3"
    adapter = MarkdownObsidianAdapter(_context())

    assert isinstance(adapter, SourceAdapter)
    assert adapter.detect(source)
    result = asyncio.run(run_import(adapter, source))

    assert not result.executed
    assert not target.exists()
    assert result.preview.source_items == 2
    assert result.preview.proposed_memories == 2
    assert result.preview.possible_secrets_flagged == 1
    assert "no source files modified" in result.preview.summary()
    assert {record.kind for record in result.preview.records} == {
        MemoryKind.DECISION,
        MemoryKind.PATTERN,
    }
    decision = next(
        record
        for record in result.preview.records
        if record.kind is MemoryKind.DECISION
    )
    assert decision.tags == ["architecture", "local-first"]
    assert decision.created_at == datetime(2026, 8, 18, 10, 30, tzinfo=timezone.utc)
    assert decision.metadata["wikilinks"] == ["Import Framework"]
    assert decision.provenance.details["format"] == "markdown"
    assert decision.provenance.details["imported_at"] == IMPORTED_AT.isoformat()
    assert decision.provenance.details["adapter_version"] == adapter.version
    assert before == {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in source.glob("*.md")
    }


def test_markdown_heading_chunking_links_parent_note(tmp_path: Path) -> None:
    note = tmp_path / "long.md"
    note.write_text(
        "# Decision\n\n"
        + ("Choose the explicit format. " * 12)
        + "\n\n# Lessons learned\n\n"
        + ("Preview before commit. " * 12)
    )
    adapter = MarkdownObsidianAdapter(_context(), chunk_threshold=100, chunk_target=180)

    records = tuple(adapter.convert(note))

    assert len(records) >= 4
    assert len({record.metadata["parent_note_id"] for record in records}) == 1
    assert all(record.metadata["chunk_count"] == len(records) for record in records)
    assert MemoryKind.DECISION in {record.kind for record in records}
    assert MemoryKind.PATTERN in {record.kind for record in records}


def test_markdown_preview_reports_duplicate_group(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("# Note\n\nThe same durable fact.\n")
    (tmp_path / "two.md").write_text("# Note\n\nThe same durable fact.\n")

    preview = MarkdownObsidianAdapter(_context()).preview(tmp_path)

    assert len(preview.duplicate_groups) == 1
    assert len(preview.duplicate_groups[0].record_ids) == 2
    assert len(set(preview.duplicate_groups[0].record_ids)) == 2


@pytest.mark.asyncio
async def test_framework_execute_and_rerun_are_idempotent(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "target" / "aoms.sqlite3")
    adapter = MarkdownObsidianAdapter(_context())
    source = FIXTURES / "markdown" / "vault"

    first = await run_import(adapter, source, execute=True, repository=repository)
    later_context = ImportContext(
        scope=Scope.WORKSPACE,
        imported_at=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc),
        actor_id="fixture-importer",
        workspace_id="fixture-workspace",
    )
    second = await run_import(
        MarkdownObsidianAdapter(later_context),
        source,
        execute=True,
        repository=repository,
    )
    stored = await repository.list(limit=100)

    assert first.records_created == 2
    assert first.records_updated == 0
    assert second.records_created == 0
    assert second.records_updated == 2
    assert {record.id for record in first.preview.records} == {
        record.id for record in second.preview.records
    }
    assert len(stored) == 2
    assert {record.id for record in stored} == {
        record.id for record in first.preview.records
    }


def test_claude_mem_fixture_preview_shows_workspace_mapping(tmp_path: Path) -> None:
    database = _claude_mem_database(tmp_path)
    adapter = ClaudeMemAdapter(_context(workspace_id=None))

    assert adapter.detect(database)
    preview = adapter.preview(database)

    assert preview.source_items == 3
    assert preview.proposed_memories == 3
    assert set(preview.workspace_mapping) == {
        "/work/client-alpha",
        "/archive/client-alpha",
    }
    assert len(set(preview.workspace_mapping.values())) == 2
    assert all(
        value.startswith("client-alpha-")
        for value in preview.workspace_mapping.values()
    )
    assert {record.scope_workspace_id for record in preview.records} == set(
        preview.workspace_mapping.values()
    )
    assert {record.provenance.record_type for record in preview.records} == {
        "observation",
        "session-summary",
    }
    assert all(
        record.provenance.details["schema_version"] == 49 for record in preview.records
    )


def test_claude_mem_workspace_override_repairs_fragmentation(tmp_path: Path) -> None:
    database = _claude_mem_database(tmp_path)
    preview = ClaudeMemAdapter(_context(workspace_id="unified-client")).preview(
        database
    )

    assert set(preview.workspace_mapping.values()) == {"unified-client"}
    assert {record.scope_workspace_id for record in preview.records} == {
        "unified-client"
    }


def test_claude_mem_refuses_unknown_schema_version(tmp_path: Path) -> None:
    database = _claude_mem_database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO schema_versions(version, applied_at) VALUES (50, ?)",
            ("2026-08-23T00:00:00Z",),
        )

    with pytest.raises(ClaudeMemSchemaError, match="version 50.*Refusing to guess"):
        ClaudeMemAdapter(_context()).preview(database)


def test_import_from_cli_dry_run_then_execute(tmp_path: Path) -> None:
    source = FIXTURES / "markdown" / "vault"
    data_dir = tmp_path / "target"
    runner = CliRunner()

    dry_run = runner.invoke(
        main,
        [
            "import-from",
            "markdown",
            str(source),
            "--scope",
            "workspace",
            "--workspace",
            "cli-workspace",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert dry_run.exit_code == 0, dry_run.output
    assert "2 source items \u2192 2 proposed memories" in dry_run.output
    assert "possible secrets flagged" in dry_run.output
    assert "Dry-run only" in dry_run.output
    assert not (data_dir / "aoms.sqlite3").exists()

    asyncio.run(SQLiteMemoryRepository(data_dir / "aoms.sqlite3").initialize())
    executed = runner.invoke(
        main,
        [
            "import-from",
            "markdown",
            str(source),
            "--scope",
            "workspace",
            "--workspace",
            "cli-workspace",
            "--execute",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert executed.exit_code == 0, executed.output
    assert "Committed 2 memories (2 new, 0 idempotent updates)" in executed.output
