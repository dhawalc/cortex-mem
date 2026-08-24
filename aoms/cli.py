"""Command-line operations for the local-first AOMS v2 store."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from aoms.application import AOMSApplication
from aoms.activation import (
    detect_invocation_source,
    host_registration_command,
    materialize_host_recipe,
    run_activation_check,
    run_host_registration,
)
from aoms.backfill import BackfillProgress, backfill_embeddings
from aoms.auth import TokenScope, TokenStore
from aoms.contest import is_expired_held, is_overdue
from aoms.contracts import (
    ContestEntry,
    ContestResolution,
    ContestState,
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallRequest,
    RememberRequest,
    SearchRequest,
    Scope,
    ScopeContext,
    SupersedeRequest,
)
from aoms.embeddings import (
    DEFAULT_FASTEMBED_MODEL,
    DEFAULT_OLLAMA_MODEL,
    EmbeddingProfile,
    NullProvider,
    provider_from_config,
)
from aoms.importer import ImportReport, JSONLImporter
from aoms.ownership import UNSCOPED_SQL, OwnershipReport, assign_ownership
from aoms.portable import PortableExportError, export_bundle, restore_bundle
from aoms.repositories.sqlite import LATEST_SCHEMA_VERSION, SQLiteMemoryRepository
from aoms.settings import AOMSSettings
from aoms.truth import (
    BOTH_ENDS_RETRIEVABLE,
    CYCLE,
    DANGLING_TARGET,
    MULTIPLE_HEADS,
    SCOPE_BOUNDARY,
    diagnose_chains,
)
from aoms.version import __version__

DEFAULT_MODEL_SIZE_MB = 67
CLAUDE_SETUP = "claude mcp add aoms -- uvx cortex-mem mcp"
OPENCLAW_SETUP = (
    "openclaw config set mcp.servers.aoms "
    '\'{"command":"uvx","args":["cortex-mem","mcp"]}\' --strict-json'
)


def _data_dir_option(function: Callable[..., Any]) -> Callable[..., Any]:
    return click.option(
        "--data-dir",
        type=click.Path(path_type=Path, file_okay=False),
        envvar="AOMS_DATA_DIR",
        help="AOMS data directory (default: platform data dir; env: AOMS_DATA_DIR).",
    )(function)


def _settings(data_dir: Path | None) -> AOMSSettings:
    environ = dict(os.environ)
    if data_dir is not None:
        environ["AOMS_DATA_DIR"] = str(data_dir)
    return AOMSSettings.load(environ)


def _repository(settings: AOMSSettings) -> SQLiteMemoryRepository:
    return SQLiteMemoryRepository(
        settings.db_path, receipt_retention=settings.receipt_retention
    )


def _scope_context() -> ScopeContext:
    return ScopeContext(
        agent_id=os.environ.get("AOMS_AGENT_ID", "").strip() or "cli",
        workspace_id=(
            os.environ.get("AOMS_WORKSPACE", "").strip() or str(Path.cwd().resolve())
        ),
    )


def _application(settings: AOMSSettings) -> AOMSApplication:
    """Build the same scoped application used by transport adapters."""

    return AOMSApplication(
        _repository(settings),
        scope_context=_scope_context(),
        embedding_provider=provider_from_config(_embedding_environment(settings)),
    )


def _idempotent_record_id(key: str, scope_context: ScopeContext) -> str:
    namespace = (
        f"cortex-mem-cli\0{scope_context.agent_id}\0{scope_context.workspace_id}\0{key}"
    )
    return "cli-" + hashlib.sha256(namespace.encode("utf-8")).hexdigest()


def _normalized_tags(values: tuple[str, ...]) -> list[str]:
    return [tag.strip() for value in values for tag in value.split(",") if tag.strip()]


def _parse_timestamp(value: str, *, parameter: str = "--as-of") -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise click.BadParameter(
            "must be an ISO-8601 timestamp, for example 2026-03-15T12:00:00Z",
            param_hint=parameter,
        ) from exc
    if parsed.tzinfo is None:
        raise click.BadParameter(
            "must include a timezone, for example a trailing Z",
            param_hint=parameter,
        )
    return parsed.astimezone(timezone.utc)


async def _remember_once(application: AOMSApplication, request: RememberRequest) -> Any:
    result = await application.remember(request)
    # A one-shot process must not abandon application-owned embedding work when
    # asyncio.run closes its loop. Provider failures remain durably queued.
    await application.wait_for_background_embeddings()
    return result


def _require_database(settings: AOMSSettings) -> None:
    if not settings.db_path.is_file():
        raise click.ClickException(
            f"AOMS is not initialized at {settings.data_dir}. "
            f"Run: cortex-mem init --data-dir {settings.data_dir}"
        )


def _embedding_environment(settings: AOMSSettings) -> dict[str, str]:
    environ = dict(os.environ)
    environ["AOMS_EMBEDDING_PROVIDER"] = settings.embedding_provider
    if settings.embedding_model:
        environ["AOMS_EMBEDDING_MODEL"] = settings.embedding_model
    if settings.embedding_dimensions:
        environ["AOMS_EMBEDDING_DIMENSIONS"] = str(settings.embedding_dimensions)
    environ["AOMS_OLLAMA_URL"] = settings.ollama_url
    return environ


def _print_host_setup() -> None:
    click.echo("\nConnect a client:")
    click.echo("  Run: cortex-mem setup claude")
    click.echo("  Or:  cortex-mem setup codex")
    click.echo("  Or:  cortex-mem setup openclaw")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="cortex-mem")
def main() -> None:
    """Local-first shared memory for MCP agent fleets.

    Start with `cortex-mem init`, then use `cortex-mem doctor` whenever
    storage, embeddings, or retrieval need an operational check.
    """


import aoms.importers.cli  # noqa: E402,F401
import aoms.ops.backup_status  # noqa: E402,F401


@main.command("init")
@_data_dir_option
def init_command(data_dir: Path | None) -> None:
    """Create the data directory and initialize the SQLite store."""

    settings = _settings(data_dir)
    existed = settings.db_path.exists()
    try:
        asyncio.run(_repository(settings).initialize())
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise click.ClickException(
            f"could not initialize {settings.db_path}: {exc}"
        ) from exc

    verb = "Checked" if existed else "Created"
    click.echo(f"{verb} AOMS data directory: {settings.data_dir}")
    click.echo(
        f"SQLite store ready (schema {LATEST_SCHEMA_VERSION}): {settings.db_path}"
    )
    if settings.embedding_provider == "fastembed":
        model = settings.embedding_model or DEFAULT_FASTEMBED_MODEL
        metadata = _fastembed_metadata(model)
        size_mb = (
            round(float(metadata.get("size_in_GB", 0.0)) * 1000)
            if metadata is not None
            else DEFAULT_MODEL_SIZE_MB
        )
        click.echo(
            f"Embedding model: {model} "
            f"(~{size_mb or DEFAULT_MODEL_SIZE_MB} MB download on first semantic "
            "operation)."
        )
        click.echo(
            "No model was downloaded by init. Run doctor to inspect cache state."
        )
    elif settings.embedding_provider == "none":
        click.echo(
            "Embeddings are disabled; search and recall will use lexical retrieval."
        )
    else:
        click.echo(
            f"Embedding provider: {settings.embedding_provider} "
            f"({settings.embedding_model or DEFAULT_OLLAMA_MODEL})."
        )
    _print_host_setup()


@main.command("setup")
@click.argument(
    "host", type=click.Choice(("claude", "codex", "openclaw"), case_sensitive=False)
)
@click.option(
    "--workspace",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    help="Workspace identity to bind (default: current directory).",
)
@_data_dir_option
def setup_command(host: str, workspace: Path | None, data_dir: Path | None) -> None:
    """Register, bind, recipe-install, and live-check one supported host."""

    normalized_host = host.casefold()
    bound_workspace = (workspace or Path.cwd()).expanduser().resolve()
    agent_id = normalized_host
    settings = _settings(data_dir)
    source = detect_invocation_source()
    try:
        asyncio.run(_repository(settings).initialize())
        recipe = materialize_host_recipe(
            normalized_host,
            settings.data_dir / "recipes",
            source=source,
            agent_id=agent_id,
            workspace=bound_workspace,
            data_dir=settings.data_dir,
        )
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise click.ClickException(f"could not prepare setup: {exc}") from exc

    click.echo(
        f"bound as agent={agent_id} workspace={bound_workspace.name} "
        f"({bound_workspace})"
    )
    click.echo(f"Source: {source.description}")
    click.echo(f"Packaged {normalized_host} recipe installed at: {recipe}")
    registration = host_registration_command(
        normalized_host,
        source,
        agent_id=agent_id,
        workspace=bound_workspace,
        data_dir=settings.data_dir,
    )
    click.echo(f"Registration: {shlex.join(registration)}")
    try:
        completed = run_host_registration(registration)
    except FileNotFoundError as exc:
        raise click.ClickException(
            f"{registration[0]} is not installed; registration was not executed"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise click.ClickException(f"host registration failed: {detail}") from exc
    if completed.stdout.strip():
        click.echo(completed.stdout.strip())
    click.echo("Registered. Starting live MCP handshake and scoped recall ...")
    try:
        activation = asyncio.run(
            run_activation_check(
                source,
                agent_id=agent_id,
                workspace=bound_workspace,
                data_dir=settings.data_dir,
                embedding_environment=_embedding_environment(settings),
            )
        )
    except Exception as exc:
        raise click.ClickException(
            f"registration succeeded but activation check failed: {exc}"
        ) from exc
    click.echo(
        f"Activated {activation.server_name} {activation.server_version}: "
        f"handshake=ok recall_sources={activation.source_count} "
        f"receipt={activation.receipt_id}"
    )
    if activation.empty_visible_store:
        click.echo(
            "Store is empty for your scopes. Next: save one durable decision with "
            "cortex-mem remember, use an importer if available, or run cortex-mem tour."
        )
    else:
        click.echo(
            "Next: start the host and ask it to recall this workspace's decisions."
        )


async def _run_tour(store: Path) -> tuple[Any, Any]:
    context = ScopeContext(agent_id="tour-agent", workspace_id="tour-workspace")
    repository = SQLiteMemoryRepository(store / "aoms.sqlite3")
    now = datetime.now(timezone.utc)
    old = MemoryRecord(
        id="tour-aurora-west",
        kind=MemoryKind.DECISION,
        content="Aurora deploy region was west.",
        tags=["tour", "aurora"],
        scope=Scope.WORKSPACE,
        scope_workspace_id=context.workspace_id,
        created_by_agent_id=context.agent_id,
        provenance=Provenance(source="disposable-tour"),
        created_at=now,
        updated_at=now,
    )
    current = old.model_copy(
        update={
            "id": "tour-aurora-east",
            "content": "Aurora deploy region is east after the latency review.",
            "supersedes": old.id,
        }
    )
    foreign = MemoryRecord(
        id="tour-private-canary",
        kind=MemoryKind.FACT,
        content="Aurora private canary must never cross the agent scope.",
        tags=["tour", "aurora"],
        scope=Scope.AGENT_PRIVATE,
        scope_agent_id="another-tour-agent",
        created_by_agent_id="another-tour-agent",
        provenance=Provenance(source="disposable-tour"),
        created_at=now,
        updated_at=now,
    )
    await repository.store_many([old, current, foreign])
    application = AOMSApplication(
        repository,
        scope_context=context,
        embedding_provider=NullProvider(),
        background_embeddings=False,
    )
    result = await application.recall(
        RecallRequest(
            task="What is the current Aurora deploy region?", token_budget=400
        )
    )
    receipt = (await application.recent_recall_receipts(limit=1))[0]
    return result, receipt


@main.command("tour")
@click.option(
    "--cleanup/--keep",
    default=True,
    show_default=True,
    help="Auto-delete the disposable demo store, or keep it for inspection.",
)
def tour_command(cleanup: bool) -> None:
    """Run a three-memory scope and supersession demo in an isolated store."""

    demo_store = Path(tempfile.mkdtemp(prefix="cortex-mem-tour-"))
    click.echo(f"DISPOSABLE DEMO store: {demo_store}")
    click.echo("The canonical AOMS store will not be opened or changed.")
    try:
        result, receipt = asyncio.run(_run_tour(demo_store))
        click.echo(
            "Seeded 3 demo memories: predecessor, current decision, private canary."
        )
        click.echo(result.context)
        click.echo(
            f"Receipt {receipt.receipt_id}: selected={len(receipt.selected)} "
            f"scope_filtered={receipt.scope_filtered_count} "
            f"superseded={len(receipt.superseded_suppressed)}"
        )
    except Exception as exc:
        raise click.ClickException(f"tour failed: {exc}") from exc
    finally:
        if cleanup:
            shutil.rmtree(demo_store, ignore_errors=True)
            click.echo(f"Auto-cleaned disposable demo store: {demo_store}")
        else:
            click.echo(f"Kept disposable demo store: {demo_store}")


@main.command("recall")
@click.option("--task", required=True, help="Describe the current task in plain language.")
@click.option(
    "--budget",
    type=click.IntRange(min=1, max=100_000),
    default=2_000,
    show_default=True,
    help="Maximum number of context tokens to pack.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(("markdown", "json"), case_sensitive=False),
    default="markdown",
    show_default=True,
)
@_data_dir_option
def recall_command(
    task: str, budget: int, output_format: str, data_dir: Path | None
) -> None:
    """Recall scoped memory as packed context for a shell hook or agent."""

    settings = _settings(data_dir)
    _require_database(settings)
    try:
        result = asyncio.run(
            _application(settings).recall(
                RecallRequest(task=task, token_budget=budget)
            )
        )
    except Exception as exc:
        raise click.ClickException(f"recall failed: {exc}") from exc
    if output_format.casefold() == "json":
        click.echo(result.model_dump_json(indent=2))
    else:
        if result.context:
            click.echo(result.context)
        elif result.diagnostics.get("empty_visible_store"):
            click.echo(
                "Store is empty for your scopes. "
                "Next: cortex-mem remember / import / tour."
            )
        else:
            click.echo("No relevant memory fit the requested recall.")


@main.command("remember")
@click.option(
    "--content",
    required=True,
    help="Durable memory text, or '-' to read UTF-8 text from stdin.",
)
@click.option(
    "--kind",
    type=click.Choice(tuple(kind.value for kind in MemoryKind), case_sensitive=False),
    default=MemoryKind.FACT.value,
    show_default=True,
)
@click.option(
    "--tags",
    multiple=True,
    help="Comma-separated tags; the option may be repeated.",
)
@click.option(
    "--idempotency-key",
    help="Stable logical-write key; retries update instead of duplicating.",
)
@click.option(
    "--claim-key",
    help=(
        "Opt this write into the contest gate as an answer to this proposition. "
        "Omit it and the write behaves exactly as it did before the gate existed."
    ),
)
@click.option(
    "--supersedes",
    help="Declare which record this write replaces on the claim slot.",
)
@_data_dir_option
def remember_command(
    content: str,
    kind: str,
    tags: tuple[str, ...],
    idempotency_key: str | None,
    claim_key: str | None,
    supersedes: str | None,
    data_dir: Path | None,
) -> None:
    """Write one selective, scoped memory from a shell hook or pipeline."""

    settings = _settings(data_dir)
    _require_database(settings)
    if content == "-":
        content = click.get_text_stream("stdin").read()
    content = content.strip()
    if not content:
        raise click.ClickException("content must not be empty")
    key = idempotency_key.strip() if idempotency_key else None
    if idempotency_key is not None and not key:
        raise click.ClickException("idempotency key must not be empty")
    scope_context = _scope_context()
    request = RememberRequest(
        id=_idempotent_record_id(key, scope_context) if key else None,
        kind=MemoryKind(kind.casefold()),
        content=content,
        tags=_normalized_tags(tags),
        provenance=Provenance(
            source="cli",
            details={"idempotency_key": key} if key else {},
        ),
        claim_key=claim_key,
        supersedes=supersedes,
    )
    try:
        result = asyncio.run(
            _remember_once(_application_with_ruleset(settings), request)
        )
    except Exception as exc:
        raise click.ClickException(f"remember failed: {exc}") from exc
    if result.contest_id is not None:
        standing = ", ".join(result.incumbent_ids) or "the existing record"
        click.echo(
            f"Stored as CONTESTED memory {result.record.id} "
            f"(kind={result.record.kind.value}, scope={result.record.scope.value})."
        )
        click.echo(f"Current memory is unchanged; {standing} still stands.")
        click.echo(f"Review: cortex-mem contest show {result.contest_id}")
        return
    action = "Created" if result.created else "Updated"
    click.echo(
        f"{action} memory {result.record.id} "
        f"(kind={result.record.kind.value}, scope={result.record.scope.value})."
    )


def _content_display(content: object) -> str:
    return content if isinstance(content, str) else json.dumps(
        content, ensure_ascii=False, sort_keys=True
    )


@main.command("supersede")
@click.argument("old_id")
@click.option(
    "--content",
    help="Corrected content; omit to prompt, or use '-' to read UTF-8 stdin.",
)
@click.option("--successor-id", help="Optional stable id for the new version.")
@_data_dir_option
def supersede_command(
    old_id: str,
    content: str | None,
    successor_id: str | None,
    data_dir: Path | None,
) -> None:
    """Append a correction linked to OLD_ID, then print its declared chain."""

    settings = _settings(data_dir)
    _require_database(settings)
    if content is None:
        content = click.prompt("New content", type=str)
    elif content == "-":
        content = click.get_text_stream("stdin").read()
    content = content.strip()
    if not content:
        raise click.ClickException("content must not be empty")
    application = _application(settings)

    async def run() -> tuple[Any, Any]:
        result = await application.supersede(
            old_id,
            SupersedeRequest(
                id=successor_id,
                content=content,
                provenance=Provenance(
                    source="cli-supersede", details={"predecessor_id": old_id}
                ),
            ),
        )
        await application.wait_for_background_embeddings()
        return result, await application.chain_timeline(result.record.id)

    try:
        result, timeline = asyncio.run(run())
    except Exception as exc:
        raise click.ClickException(f"supersede failed: {exc}") from exc
    click.echo(f"Created successor {result.record.id} superseding {old_id}.")
    click.echo(timeline.reconstruction_note)
    for version in timeline.versions:
        end = version.valid_until.isoformat() if version.valid_until else "open"
        click.echo(
            f"  {version.valid_from.isoformat()} -> {end}  {version.record.id}"
        )
        click.echo(f"    {_content_display(version.record.content)}")


def _reading_repository(settings: AOMSSettings) -> SQLiteMemoryRepository:
    """Open the store read-only for inspection commands.

    A diagnostic must never be the thing that changes the store. Opening it
    writable would apply pending migrations as a side effect of merely
    looking, which is the last behaviour you want from the command you reach
    for when you already suspect something is wrong.
    """

    return SQLiteMemoryRepository(
        settings.db_path,
        read_only=True,
        receipt_retention=settings.receipt_retention,
    )


def _application_with_ruleset(settings: AOMSSettings) -> AOMSApplication:
    return AOMSApplication(
        _repository(settings),
        scope_context=_scope_context(),
        embedding_provider=provider_from_config(_embedding_environment(settings)),
        ruleset=settings.ruleset,
    )


def _contest_display_state(entry: ContestEntry, settings: AOMSSettings) -> str:
    """Derive the reporting state. Nothing here is ever written back.

    ``expired-held`` is computed from the entry's age at the moment you look
    at it. Storing it would mean a durable state changing on a timer, which is
    exactly the shape of the endpoint that corrupted months of memory in 2026.
    """

    if entry.state is ContestState.RESOLVED:
        resolution = entry.resolution.value if entry.resolution else "resolved"
        return f"resolved ({resolution})"
    now = datetime.now(timezone.utc)
    ruleset = settings.ruleset
    if is_expired_held(entry.opened_at, now=now, ruleset=ruleset):
        return "expired-held"
    if is_overdue(entry.opened_at, now=now, ruleset=ruleset):
        return "open (overdue)"
    return "open"


def _print_contest_row(entry: ContestEntry, settings: AOMSSettings) -> None:
    age = (datetime.now(timezone.utc) - entry.opened_at).days
    click.echo(
        f"  {entry.contest_id}  {_contest_display_state(entry, settings)}  "
        f"slot={entry.claim_key}  trigger={entry.trigger.value}  "
        f"by={entry.opened_by_agent_id}  x{entry.occurrence_count}  {age}d old"
    )


@main.group("contest")
def contest_group() -> None:
    """Review and resolve contested writes. Resolution is always yours."""


@contest_group.command("list")
@click.option(
    "--state",
    type=click.Choice([item.value for item in ContestState]),
    help="Filter by stored state; 'expired-held' is derived, not stored.",
)
@click.option("--slot", "claim_key", help="Filter by claim key.")
@click.option("--by-agent", "agent_id", help="Filter by the agent that wrote it.")
@click.option("--oldest/--newest", default=True, show_default=True)
@click.option("--limit", type=click.IntRange(min=1, max=500), default=50)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@_data_dir_option
def contest_list_command(
    state: str | None,
    claim_key: str | None,
    agent_id: str | None,
    oldest: bool,
    limit: int,
    as_json: bool,
    data_dir: Path | None,
) -> None:
    """List ledger entries, oldest first so the inbox drains in order."""

    settings = _settings(data_dir)
    _require_database(settings)
    repository = _reading_repository(settings)

    async def run():
        return await repository.list_contests(
            state=ContestState(state) if state else None,
            claim_key=claim_key,
            agent_id=agent_id,
            limit=limit,
            oldest_first=oldest,
        )

    page = asyncio.run(run())
    if as_json:
        click.echo(
            json.dumps(
                {
                    "total": page.total,
                    "entries": [
                        {
                            **entry.model_dump(mode="json"),
                            "display_state": _contest_display_state(entry, settings),
                        }
                        for entry in page.entries
                    ],
                },
                indent=2,
            )
        )
        return
    click.echo(f"Contest ledger: {page.total} matching entr(ies).")
    if not page.entries:
        click.echo("  Nothing to review.")
        return
    for entry in page.entries:
        _print_contest_row(entry, settings)
    click.echo("\nInspect one with: cortex-mem contest show CONTEST_ID")


@contest_group.command("show")
@click.argument("contest_id")
@_data_dir_option
def contest_show_command(contest_id: str, data_dir: Path | None) -> None:
    """Show one entry side by side with the incumbents it did not displace."""

    settings = _settings(data_dir)
    _require_database(settings)
    repository = _reading_repository(settings)

    async def run():
        entry = await repository.get_contest(contest_id)
        if entry is None:
            raise LookupError(f"contest not found: {contest_id}")
        challenger = await repository.get(entry.record_id)
        incumbents = []
        for record_id in entry.incumbent_ids:
            record = await repository.get(record_id)
            if record is not None:
                incumbents.append(record)
        return entry, challenger, incumbents

    try:
        entry, challenger, incumbents = asyncio.run(run())
    except LookupError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Contest {entry.contest_id}")
    click.echo(f"  State:      {_contest_display_state(entry, settings)}")
    click.echo(f"  Slot:       {entry.claim_key}")
    click.echo(f"  Trigger:    {entry.trigger.value}")
    click.echo(f"  Detail:     {json.dumps(entry.trigger_detail, sort_keys=True)}")
    click.echo(f"  Opened:     {entry.opened_at.isoformat()} "
               f"by {entry.opened_by_agent_id} (x{entry.occurrence_count})")
    if entry.resolution is not None:
        click.echo(
            f"  Resolved:   {entry.resolution.value} by {entry.resolved_by} "
            f"at {entry.resolved_at.isoformat() if entry.resolved_at else '-'}"
        )
        if entry.resolution_note:
            click.echo(f"  Note:       {entry.resolution_note}")

    click.echo("\nStanding (current memory, unchanged):")
    for record in incumbents or []:
        click.echo(f"  {record.id}  {_content_display(record.content)}")
    if not incumbents:
        click.echo("  (the incumbents are no longer retrievable at this scope)")
    click.echo("\nContested (retained in full, not packed into recall):")
    if challenger is not None:
        click.echo(f"  {challenger.id}  {_content_display(challenger.content)}")

    click.echo("\nResolve with one of:")
    click.echo(f"  cortex-mem contest resolve {entry.contest_id} --admit")
    for record in incumbents or []:
        click.echo(
            f"  cortex-mem contest resolve {entry.contest_id} "
            f"--supersede {record.id}"
        )
    click.echo(
        f"  cortex-mem contest resolve {entry.contest_id} "
        '--set-aside --reason "..."'
    )
    click.echo(
        f"  cortex-mem contest resolve {entry.contest_id} --split --claim-key KEY"
    )


@contest_group.command("resolve")
@click.argument("contest_id")
@click.option("--admit", is_flag=True, help="Admit the contested record as it stands.")
@click.option(
    "--supersede",
    "supersede_id",
    help="Admit its content as a successor to this incumbent.",
)
@click.option("--set-aside", "set_aside", is_flag=True, help="Decline, reversibly.")
@click.option("--split", "split", is_flag=True, help="Re-file under another slot.")
@click.option("--claim-key", help="New claim key for --split.")
@click.option("--reason", help="Operator note recorded with the resolution.")
@_data_dir_option
def contest_resolve_command(
    contest_id: str,
    admit: bool,
    supersede_id: str | None,
    set_aside: bool,
    split: bool,
    claim_key: str | None,
    reason: str | None,
    data_dir: Path | None,
) -> None:
    """Record your verdict. Nothing else in AOMS can change a disposition."""

    chosen = [
        name
        for name, selected in (
            ("--admit", admit),
            ("--supersede", supersede_id is not None),
            ("--set-aside", set_aside),
            ("--split", split),
        )
        if selected
    ]
    if len(chosen) != 1:
        raise click.ClickException(
            "choose exactly one of --admit, --supersede, --set-aside, --split"
        )
    if split and not claim_key:
        raise click.ClickException("--split requires --claim-key")
    if set_aside and not reason:
        raise click.ClickException("--set-aside requires --reason")

    settings = _settings(data_dir)
    _require_database(settings)
    application = _application_with_ruleset(settings)
    resolver = _scope_context().agent_id

    async def run():
        entry = await application.repository.get_contest(contest_id)
        if entry is None:
            raise LookupError(f"contest not found: {contest_id}")
        result = await application.resolve_contest(
            contest_id,
            resolution=(
                ContestResolution.ADMIT
                if admit
                else ContestResolution.ADMIT_SUPERSEDING
                if supersede_id
                else ContestResolution.SET_ASIDE
                if set_aside
                else ContestResolution.SPLIT
            ),
            resolved_by=resolver,
            note=reason,
            supersede_incumbent_id=supersede_id,
            new_claim_key=claim_key,
        )
        await application.wait_for_background_embeddings()
        timeline = None
        if result.successor_id is not None:
            timeline = await application.chain_timeline(result.successor_id)
        return result, timeline

    try:
        result, timeline = asyncio.run(run())
    except Exception as exc:
        raise click.ClickException(f"resolve failed: {exc}") from exc

    click.echo(
        f"Contest {contest_id} resolved as {result.entry.resolution.value} "
        f"by {result.entry.resolved_by}."
    )
    click.echo(result.summary)
    if timeline is not None:
        click.echo(timeline.reconstruction_note)
        for version in timeline.versions:
            end = version.valid_until.isoformat() if version.valid_until else "open"
            click.echo(
                f"  {version.valid_from.isoformat()} -> {end}  {version.record.id}"
            )
            click.echo(f"    {_content_display(version.record.content)}")


@contest_group.command("drain")
@click.option("--limit", type=click.IntRange(min=1, max=200), default=10)
@_data_dir_option
def contest_drain_command(limit: int, data_dir: Path | None) -> None:
    """Print the oldest open entries with ready-to-run commands. Zero writes."""

    settings = _settings(data_dir)
    _require_database(settings)
    repository = _reading_repository(settings)

    async def run():
        return await repository.list_contests(
            state=ContestState.OPEN, limit=limit, oldest_first=True
        )

    page = asyncio.run(run())
    click.echo(f"Draining {len(page.entries)} of {page.total} open entr(ies).")
    click.echo("This command writes nothing; each verdict below is yours to run.\n")
    for entry in page.entries:
        _print_contest_row(entry, settings)
        click.echo(f"    cortex-mem contest show {entry.contest_id}")


@main.command("receipts")
@click.option("--limit", type=click.IntRange(min=1, max=1000), default=20)
@click.option("--json", "as_json", is_flag=True)
@_data_dir_option
def receipts_command(limit: int, as_json: bool, data_dir: Path | None) -> None:
    """Show recent write receipts, the append-only record of every decision."""

    settings = _settings(data_dir)
    _require_database(settings)
    repository = _reading_repository(settings)
    receipts = asyncio.run(repository.recent_write_receipts(limit=limit))
    if as_json:
        click.echo(
            json.dumps([item.model_dump(mode="json") for item in receipts], indent=2)
        )
        return
    click.echo(f"Write receipts: {len(receipts)} shown (append-only, never pruned).")
    for receipt in receipts:
        trigger = receipt.trigger.value if receipt.trigger else "-"
        click.echo(
            f"  {receipt.created_at.isoformat()}  {receipt.disposition.value:9s} "
            f"{receipt.record_id}  slot={receipt.claim_key}  trigger={trigger}"
        )


@main.command("search")
@click.argument("query")
@click.option("--limit", type=click.IntRange(min=1, max=100), default=10, show_default=True)
@click.option("--as-of", help="ISO-8601 historical boundary for declared chains.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(("text", "json"), case_sensitive=False),
    default="text",
    show_default=True,
)
@_data_dir_option
def search_command(
    query: str,
    limit: int,
    as_of: str | None,
    output_format: str,
    data_dir: Path | None,
) -> None:
    """Search scoped records, optionally at a declared-lineage boundary."""

    settings = _settings(data_dir)
    _require_database(settings)
    boundary = _parse_timestamp(as_of) if as_of else None
    try:
        result = asyncio.run(
            _application(settings).search(
                SearchRequest(query=query, limit=limit), as_of=boundary
            )
        )
    except Exception as exc:
        raise click.ClickException(f"search failed: {exc}") from exc
    if output_format.casefold() == "json":
        click.echo(result.model_dump_json(indent=2))
        return
    if boundary is not None:
        click.echo(
            "Declared-lineage reconstruction at "
            f"{boundary.isoformat()} (retained evidence, not omniscient history)."
        )
    for item in result.items:
        click.echo(
            f"{item.record.id}\t{item.record.kind.value}\t"
            f"{item.record.created_at.isoformat()}\t"
            f"{_content_display(item.record.content)}"
        )
    click.echo(f"{result.total} result(s).")


@main.command("chain")
@click.argument("record_id")
@click.option("--as-of", help="ISO-8601 historical boundary for this chain.")
@_data_dir_option
def chain_command(
    record_id: str, as_of: str | None, data_dir: Path | None
) -> None:
    """Show a scope-safe declared-lineage validity timeline."""

    settings = _settings(data_dir)
    _require_database(settings)
    boundary = _parse_timestamp(as_of) if as_of else None
    try:
        timeline = asyncio.run(
            _application(settings).chain_timeline(record_id, as_of=boundary)
        )
    except Exception as exc:
        raise click.ClickException(f"chain failed: {exc}") from exc
    click.echo(timeline.reconstruction_note)
    if boundary is not None:
        click.echo(f"Historical read boundary: {boundary.isoformat()}")
    for version in timeline.versions:
        end = version.valid_until.isoformat() if version.valid_until else "open"
        state = "active" if version.active_at_boundary else "inactive"
        click.echo(
            f"  {version.valid_from.isoformat()} -> {end}  "
            f"{version.record.id} [{state}]"
        )
        click.echo(f"    {_content_display(version.record.content)}")


@dataclass(slots=True)
class _DoctorReport:
    failures: int = 0
    warnings: int = 0

    def pass_(self, title: str, detail: str) -> None:
        click.echo(f"[PASS] {title}: {detail}")

    def warn(self, title: str, detail: str, action: str) -> None:
        self.warnings += 1
        click.echo(f"[WARN] {title}: {detail}")
        click.echo(f"       Action: {action}")

    def fail(self, title: str, detail: str, action: str) -> None:
        self.failures += 1
        click.echo(f"[FAIL] {title}: {detail}")
        click.echo(f"       Action: {action}")


def _load_sqlite_vec(connection: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec

        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        return True
    except (ImportError, sqlite3.Error):
        try:
            connection.enable_load_extension(False)
        except (AttributeError, sqlite3.Error):
            pass
        return False


def _fastembed_metadata(model: str) -> dict[str, Any] | None:
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return None
    return next(
        (
            item
            for item in TextEmbedding.list_supported_models()
            if item["model"] == model
        ),
        None,
    )


def _fastembed_cache_dir() -> Path:
    configured = os.environ.get("AOMS_EMBEDDING_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(
        os.environ.get(
            "FASTEMBED_CACHE_PATH", str(Path(tempfile.gettempdir()) / "fastembed_cache")
        )
    ).expanduser()


def _check_embedding_provider(
    report: _DoctorReport, settings: AOMSSettings
) -> EmbeddingProfile | None:
    provider = settings.embedding_provider
    if provider in {"none", "null", "disabled"}:
        report.warn(
            "Embedding provider",
            "disabled; retrieval is lexical-only",
            "Unset AOMS_EMBEDDING_PROVIDER to enable the local FastEmbed default.",
        )
        return None
    if provider == "fastembed":
        if importlib.util.find_spec("fastembed") is None:
            report.fail(
                "Embedding provider",
                "FastEmbed is not installed",
                "Reinstall cortex-mem so its fastembed dependency is present.",
            )
            return None
        model = settings.embedding_model or DEFAULT_FASTEMBED_MODEL
        metadata = _fastembed_metadata(model)
        if metadata is None:
            report.fail(
                "Embedding model",
                f"{model!r} is not supported by this FastEmbed installation",
                "Choose a model listed by FastEmbed or unset AOMS_EMBEDDING_MODEL.",
            )
            return None
        dimensions = settings.embedding_dimensions or int(metadata["dim"])
        size_mb = round(float(metadata.get("size_in_GB", 0.0)) * 1000)
        source = metadata.get("sources", {}).get("hf")
        cache_dir = _fastembed_cache_dir()
        model_file = str(metadata.get("model_file", "model_optimized.onnx"))
        cached = False
        if source:
            root = cache_dir / f"models--{str(source).replace('/', '--')}"
            cached = any(root.glob(f"snapshots/*/{model_file}"))
        if cached:
            report.pass_(
                "Embedding model",
                f"{model} is cached in {cache_dir} ({size_mb} MB model)",
            )
        else:
            report.warn(
                "Embedding model",
                f"{model} is not cached; the first semantic operation downloads "
                f"approximately {size_mb or DEFAULT_MODEL_SIZE_MB} MB",
                "Import memories, then run `cortex-mem backfill` when ready "
                "to download.",
            )
        report.pass_(
            "Embedding provider", f"FastEmbed is available ({dimensions} dimensions)"
        )
        return EmbeddingProfile("fastembed", model, dimensions)
    if provider == "ollama":
        model = settings.embedding_model or DEFAULT_OLLAMA_MODEL
        dimensions = settings.embedding_dimensions or 768
        try:
            import httpx

            response = httpx.get(
                f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=2.0
            )
            response.raise_for_status()
            names = {
                str(item.get("name") or item.get("model"))
                for item in response.json().get("models", [])
                if isinstance(item, dict)
            }
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            report.fail(
                "Embedding provider",
                f"Ollama is unavailable at {settings.ollama_url}: {exc}",
                "Start Ollama or set AOMS_EMBEDDING_PROVIDER=fastembed.",
            )
            return None
        if model not in names and f"{model}:latest" not in names:
            report.fail(
                "Embedding model",
                f"Ollama is running but {model!r} is not installed",
                f"Run: ollama pull {model}",
            )
        else:
            report.pass_("Embedding model", f"Ollama model {model} is installed")
        report.pass_(
            "Embedding provider", f"Ollama is available at {settings.ollama_url}"
        )
        return EmbeddingProfile("ollama", model, dimensions)
    report.fail(
        "Embedding provider",
        f"unknown provider {provider!r}",
        "Set AOMS_EMBEDDING_PROVIDER to fastembed, ollama, or none.",
    )
    return None


def _doctor_database(
    report: _DoctorReport,
    settings: AOMSSettings,
    profile: EmbeddingProfile | None,
) -> None:
    init_command_text = f"cortex-mem init --data-dir {settings.data_dir}"
    if not settings.data_dir.is_dir():
        report.fail(
            "Data directory",
            f"missing: {settings.data_dir}",
            f"Run: {init_command_text}",
        )
        return
    if not os.access(settings.data_dir, os.R_OK | os.W_OK | os.X_OK):
        report.fail(
            "Data directory",
            f"not readable and writable: {settings.data_dir}",
            "Fix directory ownership and permissions, then rerun doctor.",
        )
    else:
        report.pass_("Data directory", f"readable and writable: {settings.data_dir}")
    if not settings.db_path.is_file():
        report.fail(
            "SQLite store", f"missing: {settings.db_path}", f"Run: {init_command_text}"
        )
        return

    try:
        uri = f"{settings.db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        report.fail(
            "SQLite store",
            f"cannot open {settings.db_path}: {exc}",
            "Restore a verified export into a new data directory.",
        )
        return
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            report.fail(
                "Database integrity",
                integrity,
                "Stop using this store and restore a verified export into a new "
                "data directory.",
            )
            return
        report.pass_("Database integrity", "SQLite integrity_check returned ok")
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        required = {"schema_version", "memories", "memories_fts", "recall_receipts"}
        missing = required - tables
        if missing:
            report.fail(
                "Database schema",
                f"missing objects: {', '.join(sorted(missing))}",
                f"Back up the file, then run: {init_command_text}",
            )
            return
        schema_version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_version"
            ).fetchone()[0]
        )
        if schema_version != LATEST_SCHEMA_VERSION:
            report.fail(
                "Schema version",
                f"found {schema_version}; this CLI expects {LATEST_SCHEMA_VERSION}",
                f"Run: {init_command_text}",
            )
        else:
            report.pass_("Schema version", str(schema_version))

        total = int(connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        if total == 0:
            import_action = (
                "Run `cortex-mem import-from markdown PATH --scope workspace` to "
                "bring existing notes, or connect a client and call remember."
                if "import-from" in getattr(main, "commands", {})
                else "Run `cortex-mem import PATH` or connect a client and call remember."
            )
            report.warn(
                "Memory records",
                "store is healthy but empty",
                import_action,
            )
        else:
            report.pass_("Memory records", f"{total} canonical records")

        updated_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM memories WHERE updated_at <> created_at"
            ).fetchone()[0]
        )
        if updated_count:
            updated_ids = [
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM memories WHERE updated_at <> created_at "
                    "ORDER BY id LIMIT 5"
                ).fetchall()
            ]
            samples = ", ".join(updated_ids)
            if updated_count > 5:
                samples += f", +{updated_count - 5} more"
            report.warn(
                "In-place update signal",
                f"{updated_count} record(s) have updated_at != created_at: "
                f"{samples}",
                "This can be legitimate for a trusted importer or idempotent "
                "restore/upsert. Otherwise investigate provenance and compare "
                "backup generations using docs/RECOVERY.md.",
            )
        else:
            report.pass_(
                "In-place update signal", "0 records have updated_at != created_at"
            )

        unscoped = int(
            connection.execute(
                f"SELECT COUNT(*) FROM memories WHERE {UNSCOPED_SQL}"
            ).fetchone()[0]
        )
        if unscoped:
            report.warn(
                "Unscoped records",
                f"{unscoped} record(s) are excluded from scoped reads",
                "Run: cortex-mem assign-ownership --scope user-global --execute "
                f"--data-dir {settings.data_dir}",
            )
        else:
            report.pass_("Unscoped records", "0 records")

        record_rows = connection.execute(
            "SELECT record_json FROM memories ORDER BY id"
        ).fetchall()
        fts_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT id FROM memories_fts ORDER BY id"
            ).fetchall()
        }
        chain_health = diagnose_chains(
            (
                MemoryRecord.model_validate_json(row["record_json"])
                for row in record_rows
            ),
            fts_memory_ids=fts_ids,
        )
        chain_categories = (
            (CYCLE, "Supersession cycles"),
            (DANGLING_TARGET, "Dangling supersedes targets"),
            (MULTIPLE_HEADS, "Multiple apparent heads"),
            (BOTH_ENDS_RETRIEVABLE, "Both-ends-retrievable pairs"),
            (SCOPE_BOUNDARY, "Scope-boundary anomalies"),
        )
        for category, title in chain_categories:
            findings = [
                finding
                for finding in chain_health.findings
                if finding.category == category
            ]
            if not findings:
                report.pass_(title, "0 deterministic finding(s)")
                continue
            samples = "; ".join(
                f"{','.join(item.record_ids)} ({item.detail})"
                for item in findings[:5]
            )
            if len(findings) > 5:
                samples += f"; +{len(findings) - 5} more"
            report.warn(
                title,
                f"{len(findings)} deterministic finding(s): {samples}",
                "Inspect linked records in `cortex-mem observe`; no auto-fix is "
                "performed.",
            )

        receipt_count = int(
            connection.execute("SELECT COUNT(*) FROM recall_receipts").fetchone()[0]
        )
        if receipt_count > settings.receipt_retention:
            report.warn(
                "Receipt store",
                f"{receipt_count} receipts exceeds retention "
                f"{settings.receipt_retention}",
                "Run: cortex-mem sweep",
            )
        else:
            report.pass_(
                "Receipt store",
                f"available ({receipt_count} receipts; retention "
                f"{settings.receipt_retention})",
            )

        if profile is None:
            report.warn(
                "Vector coverage",
                "not applicable while embeddings are unavailable or disabled",
                "Resolve the embedding-provider finding above, then run "
                "`cortex-mem backfill`.",
            )
            return
        pending = int(
            connection.execute(
                "SELECT COUNT(*) FROM embedding_pending WHERE profile_key = ?",
                (profile.key,),
            ).fetchone()[0]
        )
        if pending:
            report.warn(
                "Embedding queue",
                f"{pending} pending record(s) for {profile.key}",
                "Run: cortex-mem sweep",
            )
        else:
            report.pass_("Embedding queue", "0 pending records")

        vector_count = 0
        vector_table = f"memory_vectors_{profile.dimensions}"
        if _load_sqlite_vec(connection) and vector_table in tables:
            vector_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {vector_table} AS v "
                    "JOIN memories AS m ON m.id = v.memory_id "
                    "WHERE v.profile_key = ? AND v.record_updated_at = m.updated_at",
                    (profile.key,),
                ).fetchone()[0]
            )
        coverage = 1.0 if total == 0 else vector_count / total
        detail = f"{vector_count}/{total} current records ({coverage:.1%})"
        if total and vector_count < total:
            report.warn("Vector coverage", detail, "Run: cortex-mem backfill")
        else:
            report.pass_("Vector coverage", detail)
    except sqlite3.DatabaseError as exc:
        report.fail(
            "SQLite store",
            f"database read failed: {exc}",
            "Restore a verified export into a new data directory; do not "
            "overwrite this file.",
        )
    finally:
        connection.close()


def _doctor_contests(report: _DoctorReport, settings: AOMSSettings) -> None:
    """Surface the ledger in the same pass/warn/fail reporter as everything else."""

    repository = _reading_repository(settings)

    async def run():
        # Deliberately not `integrity_report()`: that also walks the FTS and
        # vector projections, which is minutes of work on a large store, and
        # doctor runs this check every time.
        drift, contested_count, _ = await repository.contested_drift_report()
        page = await repository.list_contests(
            state=ContestState.OPEN, limit=500, oldest_first=True
        )
        return drift, contested_count, page

    try:
        drift, contested_count, page = asyncio.run(run())
    except sqlite3.DatabaseError as exc:
        report.fail(
            "Contest ledger",
            f"could not be read: {exc}",
            "Restore a verified export into a new data directory.",
        )
        return

    if drift:
        named = ", ".join(drift[:10])
        extra = f" (+{len(drift) - 10} more)" if len(drift) > 10 else ""
        report.fail(
            "Contested projection",
            f"{len(drift)} record(s) disagree with the ledger: {named}{extra}",
            "Do not write to this store. Run `cortex-mem contest list` and "
            "reconcile before any further writes.",
        )
    else:
        report.pass_(
            "Contested projection",
            f"agrees with the ledger ({contested_count} contested record(s))",
        )

    now = datetime.now(timezone.utc)
    ruleset = settings.ruleset
    overdue = [
        entry
        for entry in page.entries
        if is_overdue(entry.opened_at, now=now, ruleset=ruleset)
    ]
    if overdue:
        oldest = min(entry.opened_at for entry in overdue)
        report.fail(
            "Contest inbox",
            f"{len(overdue)} of {page.total} open entr(ies) are past the "
            f"{ruleset.contest_sla_days}-day review window "
            f"(oldest opened {oldest.date().isoformat()})",
            "Review them: cortex-mem contest drain. Nothing resolves on a "
            "timer; a person decides each one.",
        )
    elif page.total:
        report.warn(
            "Contest inbox",
            f"{page.total} open entr(ies) awaiting review",
            "Review them: cortex-mem contest drain",
        )
    else:
        report.pass_("Contest inbox", "no open entries")


@main.command("doctor")
@click.option(
    "--contests",
    "contests",
    is_flag=True,
    help="Print the projected disposition map for every claim slot. Zero writes.",
)
@_data_dir_option
def doctor_command(contests: bool, data_dir: Path | None) -> None:
    """Diagnose storage, schema, embeddings, vectors, queues, and receipts."""

    settings = _settings(data_dir)
    if contests:
        _print_disposition_map(settings)
        return
    click.echo(f"AOMS doctor {__version__}")
    click.echo(f"Data directory: {settings.data_dir}\n")
    report = _DoctorReport()
    profile = _check_embedding_provider(report, settings)
    _doctor_database(report, settings, profile)
    if settings.db_path.is_file():
        _doctor_contests(report, settings)
    click.echo(
        f"\nDoctor finished: {report.failures} failure(s), "
        f"{report.warnings} warning(s)."
    )
    if report.failures:
        raise click.exceptions.Exit(1)


def _print_disposition_map(settings: AOMSSettings) -> None:
    """Read-only projection of which record holds which slot, and what does not."""

    _require_database(settings)
    click.echo(f"AOMS disposition map {__version__}")
    click.echo(f"Data directory: {settings.data_dir}")
    click.echo("Dry run: this command performs zero writes.\n")

    with sqlite3.connect(
        f"{settings.db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0
    ) as connection:
        connection.row_factory = sqlite3.Row
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(memories)").fetchall()
        }
        if "claim_key" not in columns:
            click.echo("This store predates the contest ledger; nothing participates.")
            return
        rows = connection.execute(
            "SELECT claim_key, scope, scope_agent_id, scope_workspace_id, "
            "contested, COUNT(*) AS count FROM memories "
            "WHERE claim_key IS NOT NULL "
            "GROUP BY claim_key, scope, scope_agent_id, scope_workspace_id, contested "
            "ORDER BY claim_key ASC, contested ASC"
        ).fetchall()
        non_participating = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM memories WHERE claim_key IS NULL"
            ).fetchone()["count"]
        )

    click.echo(
        f"{non_participating} record(s) do not participate in the gate "
        "(claim_key IS NULL) and behave exactly as they did before it existed.\n"
    )
    if not rows:
        click.echo("No record declares a claim key yet.")
        return
    slots: dict[tuple[str, str, str | None, str | None], dict[str, int]] = {}
    for row in rows:
        key = (
            str(row["claim_key"]),
            str(row["scope"]),
            row["scope_agent_id"],
            row["scope_workspace_id"],
        )
        bucket = slots.setdefault(key, {"admitted": 0, "contested": 0})
        label = "contested" if int(row["contested"]) else "admitted"
        bucket[label] += int(row["count"])
    click.echo(f"{len(slots)} claim slot(s):")
    for (claim_key, scope, agent_id, workspace_id), counts in slots.items():
        binding = agent_id or workspace_id or "user-global"
        click.echo(
            f"  {claim_key}  [{scope} {binding}]  "
            f"admitted={counts['admitted']}  contested={counts['contested']}"
        )


def _format_ownership_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{name}={count}" for name, count in counts.items()) or "none"


def _print_ownership_report(report: OwnershipReport) -> None:
    mode = "DRY RUN" if report.dry_run else "EXECUTE"
    click.echo(f"Ownership assignment ({mode})")
    click.echo(f"Scope: {report.scope}")
    click.echo(
        f"Before: {report.before.unscoped_records} unscoped record(s); "
        f"by kind: {_format_ownership_counts(report.before.by_kind)}; "
        f"by tier: {_format_ownership_counts(report.before.by_tier)}"
    )
    click.echo(
        f"After: {report.after.unscoped_records} unscoped record(s); "
        f"by kind: {_format_ownership_counts(report.after.by_kind)}; "
        f"by tier: {_format_ownership_counts(report.after.by_tier)}"
    )
    if report.dry_run:
        click.echo(
            f"Dry run: would assign {report.would_assign} record(s); wrote 0. "
            "Pass --execute to commit."
        )
    else:
        click.echo(f"Assigned: {report.assigned_records} record(s).")
    click.echo(f"Remaining unscoped: {report.remaining_unscoped}")
    click.echo("JSON report:")
    click.echo(json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":")))


@main.command("assign-ownership")
@click.option(
    "--scope",
    type=click.Choice((Scope.USER_GLOBAL.value,)),
    required=True,
    help="Bulk assignment scope; only user-global is trusted for legacy imports.",
)
@click.option(
    "--dry-run/--execute",
    default=True,
    show_default=True,
    help="Preview by default; --execute is required to write any record.",
)
@click.option(
    "--batch-size", type=click.IntRange(min=1), default=500, show_default=True
)
@_data_dir_option
def assign_ownership_command(
    scope: str,
    dry_run: bool,
    batch_size: int,
    data_dir: Path | None,
) -> None:
    """Assign legacy unscoped records to the fleet-shared user scope.

    Agent-private and workspace bulk assignment are deliberately unavailable:
    without per-record knowledge, restrictive scopes would fabricate ownership
    claims. Every committed batch is atomic, and completed records are skipped
    on resume.
    """

    settings = _settings(data_dir)
    _require_database(settings)
    assignment_timestamp = datetime.now(timezone.utc).isoformat()
    try:
        result = asyncio.run(
            assign_ownership(
                _repository(settings),
                scope=Scope(scope),
                dry_run=dry_run,
                batch_size=batch_size,
                assignment_timestamp=assignment_timestamp,
                tool_version=__version__,
            )
        )
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        raise click.ClickException(f"ownership assignment failed: {exc}") from exc
    _print_ownership_report(result)
    if not dry_run and result.remaining_unscoped:
        raise click.exceptions.Exit(1)


@main.group("token")
def token_group() -> None:
    """Create, inspect, and revoke remote MCP bearer tokens.

    These commands require local access to the AOMS data directory. The admin
    scope is reserved for future remote maintenance endpoints.
    """


def _parse_expiry(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise click.BadParameter(
            "must be an ISO-8601 timestamp, for example 2026-09-01T12:00:00Z",
            param_hint="--expires-at",
        ) from exc
    if parsed.tzinfo is None:
        raise click.BadParameter(
            "must include a timezone, for example a trailing Z",
            param_hint="--expires-at",
        )
    return parsed.astimezone(timezone.utc)


@token_group.command("create")
@click.argument("name")
@click.option(
    "--scope",
    "scopes",
    type=click.Choice([scope.value for scope in TokenScope]),
    multiple=True,
    required=True,
    help="Grant a scope; repeat for multiple scopes.",
)
@click.option("--agent-id", help="Agent identity bound to the token.")
@click.option("--workspace-id", help="Workspace identity bound to the token.")
@click.option("--expires-at", help="Optional ISO-8601 expiry timestamp.")
@_data_dir_option
def token_create_command(
    name: str,
    scopes: tuple[str, ...],
    agent_id: str | None,
    workspace_id: str | None,
    expires_at: str | None,
    data_dir: Path | None,
) -> None:
    """Create a token and print its bearer secret exactly once."""

    settings = _settings(data_dir)
    _require_database(settings)
    process_scope = _scope_context()
    try:
        created = asyncio.run(
            TokenStore(settings.db_path).create(
                name=name,
                scopes=scopes,
                agent_id=agent_id or process_scope.agent_id,
                workspace_id=workspace_id or process_scope.workspace_id,
                expires_at=_parse_expiry(expires_at),
            )
        )
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        raise click.ClickException(f"could not create token: {exc}") from exc
    record = created.token
    click.echo(f"Created token {record.token_id} ({record.name}).")
    click.echo(f"Scopes: {','.join(record.scopes)}")
    click.echo(
        f"Identity: agent_id={record.agent_id} workspace_id={record.workspace_id}"
    )
    click.echo("Bearer token (shown once):")
    click.echo(created.secret)


@token_group.command("list")
@_data_dir_option
def token_list_command(data_dir: Path | None) -> None:
    """List token metadata without exposing bearer secrets or hashes."""

    settings = _settings(data_dir)
    _require_database(settings)
    try:
        records = asyncio.run(TokenStore(settings.db_path).list())
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise click.ClickException(f"could not list tokens: {exc}") from exc
    if not records:
        click.echo("No tokens configured.")
        return
    click.echo(
        "TOKEN_ID         STATUS   SCOPES           AGENT / WORKSPACE             NAME"
    )
    for record in records:
        identity = f"{record.agent_id} / {record.workspace_id}"
        click.echo(
            f"{record.token_id:<16} {record.status:<8} "
            f"{','.join(record.scopes):<16} {identity:<29} {record.name}"
        )
        click.echo(
            " " * 17
            + f"created={record.created_at.isoformat()} "
            + "last_used="
            + (record.last_used_at.isoformat() if record.last_used_at else "-")
            + " "
            + f"expires={record.expires_at.isoformat() if record.expires_at else '-'}"
        )


@token_group.command("revoke")
@click.argument("token_id")
@_data_dir_option
def token_revoke_command(token_id: str, data_dir: Path | None) -> None:
    """Permanently revoke a token by its non-secret token id."""

    settings = _settings(data_dir)
    _require_database(settings)
    try:
        revoked = asyncio.run(TokenStore(settings.db_path).revoke(token_id))
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise click.ClickException(f"could not revoke token: {exc}") from exc
    if not revoked:
        raise click.ClickException(f"active token not found: {token_id}")
    click.echo(f"Revoked token {token_id}.")


@main.command("import")
@click.argument("source", type=click.Path(path_type=Path, exists=True, file_okay=False))
@click.option(
    "--batch-size", type=click.IntRange(min=1), default=500, show_default=True
)
@_data_dir_option
def import_command(source: Path, batch_size: int, data_dir: Path | None) -> None:
    """Import a reviewed legacy JSONL corpus into the canonical store."""

    settings = _settings(data_dir)
    _require_database(settings)

    def progress(path: Path, report: ImportReport) -> None:
        click.echo(
            f"  {path.as_posix()}: {report.records_upserted} record(s) imported so far"
        )

    importer = JSONLImporter(
        _repository(settings),
        scope_context=_scope_context(),
        batch_size=batch_size,
        progress=progress,
    )
    click.echo(f"Importing JSONL from {source.resolve()} ...")
    try:
        result = asyncio.run(importer.import_directory(source))
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        raise click.ClickException(f"import failed: {exc}") from exc
    click.echo(
        f"Imported {result.records_upserted}/{result.records_seen} record(s) "
        f"from {result.files_scanned} file(s); {len(result.issues)} issue(s)."
    )
    for issue in result.issues[:20]:
        click.echo(
            f"  Warning: {issue.source_file}:{issue.line_number}: {issue.message}",
            err=True,
        )
    if len(result.issues) > 20:
        click.echo(
            f"  Warning: {len(result.issues) - 20} more issue(s) omitted.", err=True
        )


def _print_backfill_progress(item: BackfillProgress) -> None:
    click.echo(
        f"  {item.phase}: scanned={item.scanned} queued={item.queued} "
        f"embedded={item.embedded} failed={item.failed} pending={item.pending}"
    )


async def _run_backfill(
    settings: AOMSSettings, batch_size: int, max_batches: int | None
) -> Any:
    provider = provider_from_config(_embedding_environment(settings))
    repository = _repository(settings)
    await repository.initialize()
    return await backfill_embeddings(
        repository,
        provider,
        batch_size=batch_size,
        progress=_print_backfill_progress,
        max_batches=max_batches,
    )


@main.command("backfill")
@click.option("--batch-size", type=click.IntRange(min=1), default=64, show_default=True)
@click.option("--max-batches", type=click.IntRange(min=1), default=None)
@_data_dir_option
def backfill_command(
    batch_size: int, max_batches: int | None, data_dir: Path | None
) -> None:
    """Embed every missing or stale memory; safe to interrupt and resume."""

    settings = _settings(data_dir)
    _require_database(settings)
    click.echo("Catching up embeddings ...")
    try:
        result = asyncio.run(_run_backfill(settings, batch_size, max_batches))
    except Exception as exc:
        raise click.ClickException(f"backfill failed: {exc}") from exc
    click.echo(
        f"Backfill finished: scanned={result.scanned} queued={result.queued} "
        f"embedded={result.embedded} failed={result.failed} pending={result.pending}."
    )
    if result.failed:
        raise click.exceptions.Exit(1)


@main.command("sweep")
@click.option("--batch-size", type=click.IntRange(min=1), default=64, show_default=True)
@click.option("--max-batches", type=click.IntRange(min=1), default=None)
@_data_dir_option
def sweep_command(
    batch_size: int, max_batches: int | None, data_dir: Path | None
) -> None:
    """Catch up embeddings and prune receipts to the retention limit."""

    settings = _settings(data_dir)
    _require_database(settings)
    repository = _repository(settings)
    try:
        result = asyncio.run(_run_backfill(settings, batch_size, max_batches))
        prune_report = asyncio.run(
            repository.prune_recall_receipts(retain=settings.receipt_retention)
        )
    except Exception as exc:
        raise click.ClickException(f"sweep failed: {exc}") from exc
    click.echo(
        f"Sweep finished: embedded={result.embedded}, failed={result.failed}, "
        f"pending={result.pending}, receipts_pruned={prune_report.deleted_count}."
    )
    if result.failed:
        raise click.exceptions.Exit(1)


@main.command("export")
@click.argument("destination", type=click.Path(path_type=Path, file_okay=False))
@_data_dir_option
def export_command(destination: Path, data_dir: Path | None) -> None:
    """Write records, receipts, and a SHA-256 manifest to a portable bundle."""

    settings = _settings(data_dir)
    _require_database(settings)
    try:
        result = asyncio.run(export_bundle(_repository(settings), destination))
    except (OSError, RuntimeError, sqlite3.Error, PortableExportError) as exc:
        raise click.ClickException(f"export failed: {exc}") from exc
    click.echo(
        f"Exported {result.records} record(s) and {result.receipts} receipt(s) "
        f"to {result.destination} (manifest.json uses SHA-256)."
    )


@main.command("restore")
@click.argument("source", type=click.Path(path_type=Path, exists=True, file_okay=False))
@click.option(
    "--batch-size", type=click.IntRange(min=1), default=500, show_default=True
)
@_data_dir_option
def restore_command(source: Path, batch_size: int, data_dir: Path | None) -> None:
    """Validate a portable manifest, then restore into an empty store."""

    settings = _settings(data_dir)
    try:
        result = asyncio.run(
            restore_bundle(_repository(settings), source, batch_size=batch_size)
        )
    except (
        OSError,
        RuntimeError,
        sqlite3.Error,
        PortableExportError,
        ValueError,
    ) as exc:
        raise click.ClickException(f"restore failed: {exc}") from exc
    click.echo(
        f"Restored {result.records} record(s) and {result.receipts} receipt(s) "
        f"into {settings.db_path}. Run `cortex-mem backfill` to rebuild vectors."
    )


def _mcp_entrypoint(module: Any) -> Callable[..., Any] | None:
    for name in ("main", "run"):
        value = getattr(module, name, None)
        if callable(value):
            return value
    for name in ("mcp", "server"):
        value = getattr(module, name, None)
        run = getattr(value, "run", None)
        if callable(run):
            return run
    return None


@main.command(
    "mcp", context_settings={"ignore_unknown_options": True, "allow_extra_args": True}
)
@click.pass_context
def mcp_command(context: click.Context) -> None:
    """Run the MCP adapter (stdio by default; HTTP via forwarded options)."""

    module = None
    module_name = ""
    for candidate in (
        "aoms.adapters.mcp_server",
        "aoms.mcp_server",
        "aoms.mcp",
    ):
        try:
            spec = importlib.util.find_spec(candidate)
        except ModuleNotFoundError:
            spec = None
        if spec is not None:
            module_name = candidate
            try:
                module = importlib.import_module(candidate)
            except Exception as exc:
                raise click.ClickException(
                    f"MCP adapter {candidate} is present but failed to load: {exc}"
                ) from exc
            break
    if module is None:
        raise click.ClickException(
            "MCP adapter not merged yet. The CLI/package is ready, but this branch "
            "does not contain aoms.adapters.mcp_server, aoms.mcp_server, or aoms.mcp."
        )
    entrypoint = _mcp_entrypoint(module)
    if entrypoint is None:
        raise click.ClickException(
            f"MCP adapter {module_name} has no main(), run(), or server.run() "
            "entry point."
        )
    original_argv = sys.argv
    sys.argv = [f"cortex-mem {module_name}", *context.args]
    try:
        result = entrypoint()
        if inspect.isawaitable(result):
            result = asyncio.run(result)
    finally:
        sys.argv = original_argv
    if isinstance(result, int) and result:
        raise click.exceptions.Exit(result)


from aoms.observatory.cli import observe_command as _observe_command  # noqa: E402

main.add_command(_observe_command)


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["CLAUDE_SETUP", "OPENCLAW_SETUP", "main"]
