"""Click command for preview-first source imports.

The root CLI imports this module once after creating its Click group. Registration
stays here so parallel CLI work only needs a one-line integration point.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

import click

from aoms.contracts import Scope
from aoms.repositories import SQLiteMemoryRepository
from aoms.settings import AOMSSettings

from .base import ImportContext, ImportResult, run_import
from .claude_mem import ClaudeMemAdapter, ClaudeMemSchemaError
from .markdown import MarkdownObsidianAdapter


def _settings(data_dir: Path | None) -> AOMSSettings:
    environ = dict(os.environ)
    if data_dir is not None:
        environ["AOMS_DATA_DIR"] = str(data_dir)
    return AOMSSettings.load(environ)


def _adapter(
    source: str,
    *,
    context: ImportContext,
) -> MarkdownObsidianAdapter | ClaudeMemAdapter:
    if source in {"markdown", "obsidian"}:
        return MarkdownObsidianAdapter(context)
    return ClaudeMemAdapter(context)


def _print_report(result: ImportResult, target: Path) -> None:
    preview = result.preview
    mode = "execute" if result.executed else "dry-run"
    click.echo(f"Import preview ({mode})")
    click.echo(f"Adapter: {preview.adapter} ({preview.adapter_version})")
    click.echo(f"Source: {preview.source_path}")
    click.echo(preview.summary())
    if preview.workspace_mapping:
        click.echo("Proposed workspace mapping:")
        for source_project, workspace in preview.workspace_mapping.items():
            click.echo(f"  {source_project} -> {workspace}")
    for group in preview.duplicate_groups:
        click.echo(
            f"Duplicate group {group.fingerprint[:12]}: "
            f"{len(group.record_ids)} proposed memories"
        )
    for warning in preview.secret_warnings:
        click.echo(
            f"Warning: possible {warning.pattern} in {warning.source}:"
            f"{warning.line_number} (value not shown)",
            err=True,
        )
    click.echo(f"Import target: {target}")
    if result.executed:
        click.echo(
            f"Committed {result.records_committed} memories "
            f"({result.records_created} new, {result.records_updated} idempotent updates)."
        )
    else:
        click.echo(
            "Dry-run only. Re-run with --execute to commit this source proposal."
        )


@click.command("import-from")
@click.argument("source", type=click.Choice(["markdown", "obsidian", "claude-mem"]))
@click.argument("path", type=click.Path(path_type=Path, exists=True))
@click.option(
    "--scope",
    type=click.Choice([Scope.WORKSPACE.value, Scope.USER_GLOBAL.value]),
    required=True,
    help="Required destination scope choice.",
)
@click.option(
    "--workspace",
    help=(
        "Destination workspace ID. For claude-mem, this merges every source "
        "project into one workspace; omit to preview deterministic per-project IDs."
    ),
)
@click.option(
    "--execute",
    is_flag=True,
    help="Commit the previewed records. Without this flag, the command is read-only.",
)
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path, file_okay=False),
    envvar="AOMS_DATA_DIR",
    help="AOMS data directory (default: platform data dir; env: AOMS_DATA_DIR).",
)
def import_from_command(
    source: str,
    path: Path,
    scope: str,
    workspace: str | None,
    execute: bool,
    data_dir: Path | None,
) -> None:
    """Preview or import SOURCE memories from the explicitly selected PATH."""

    workspace = workspace.strip() if workspace else None
    chosen_scope = Scope(scope)
    if chosen_scope is Scope.USER_GLOBAL and workspace:
        raise click.ClickException("--workspace cannot be used with user-global scope")
    actor = os.environ.get("AOMS_AGENT_ID", "").strip() or "source-importer"
    context = ImportContext.now(
        chosen_scope,
        actor_id=actor,
        workspace_id=workspace,
    )
    adapter = _adapter(source, context=context)
    settings = _settings(data_dir)
    repository = None
    if execute:
        if not settings.db_path.is_file():
            raise click.ClickException(
                f"AOMS is not initialized at {settings.data_dir}. "
                f"Run: cortex-mem init --data-dir {settings.data_dir}"
            )
        repository = SQLiteMemoryRepository(
            settings.db_path,
            receipt_retention=settings.receipt_retention,
            receipt_byte_budget=settings.receipt_byte_budget,
        )
    try:
        result = asyncio.run(
            run_import(adapter, path, execute=execute, repository=repository)
        )
    except (
        ClaudeMemSchemaError,
        OSError,
        RuntimeError,
        sqlite3.Error,
        UnicodeError,
        ValueError,
    ) as exc:
        raise click.ClickException(f"import-from failed: {exc}") from exc
    _print_report(result, settings.db_path)


# ``python -m aoms.cli`` runs the root as ``__main__``; the installed console script
# imports it as ``aoms.cli``. Support both without adding a second root integration line.
_root_main = getattr(sys.modules.get("__main__"), "main", None)
if not isinstance(_root_main, click.Group):
    from aoms.cli import main as _root_main  # noqa: E402

_root_main.add_command(import_from_command)
