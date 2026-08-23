"""Command-line operations for the local-first AOMS v2 store."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import os
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from aoms.backfill import BackfillProgress, backfill_embeddings
from aoms.auth import TokenScope, TokenStore
from aoms.contracts import ScopeContext
from aoms.embeddings import (
    DEFAULT_FASTEMBED_MODEL,
    DEFAULT_OLLAMA_MODEL,
    EmbeddingProfile,
    provider_from_config,
)
from aoms.importer import ImportReport, JSONLImporter
from aoms.portable import PortableExportError, export_bundle, restore_bundle
from aoms.repositories.sqlite import LATEST_SCHEMA_VERSION, SQLiteMemoryRepository
from aoms.settings import AOMSSettings
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
        agent_id=os.environ.get("AOMS_AGENT_ID", "").strip() or "default",
        workspace_id=os.environ.get("AOMS_WORKSPACE", "").strip() or "default",
    )


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
    click.echo(f"  Claude Code: {CLAUDE_SETUP}")
    click.echo(f"  OpenClaw:    {OPENCLAW_SETUP}")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="cortex-mem")
def main() -> None:
    """Local-first shared memory for MCP agent fleets.

    Start with `cortex-mem init`, then use `cortex-mem doctor` whenever
    storage, embeddings, or retrieval need an operational check.
    """


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
            report.warn(
                "Memory records",
                "store is healthy but empty",
                "Run `cortex-mem import PATH` or connect a client and call remember.",
            )
        else:
            report.pass_("Memory records", f"{total} canonical records")

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


@main.command("doctor")
@_data_dir_option
def doctor_command(data_dir: Path | None) -> None:
    """Diagnose storage, schema, embeddings, vectors, queues, and receipts."""

    settings = _settings(data_dir)
    click.echo(f"AOMS doctor {__version__}")
    click.echo(f"Data directory: {settings.data_dir}\n")
    report = _DoctorReport()
    profile = _check_embedding_provider(report, settings)
    _doctor_database(report, settings, profile)
    click.echo(
        f"\nDoctor finished: {report.failures} failure(s), "
        f"{report.warnings} warning(s)."
    )
    if report.failures:
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


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["CLAUDE_SETUP", "OPENCLAW_SETUP", "main"]
