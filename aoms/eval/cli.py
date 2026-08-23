"""Command-line interface for running and comparing retrieval evaluations."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import click

from aoms.repositories.sqlite import SQLiteMemoryRepository

from .corpus import generate_corpus
from .models import CorpusManifest
from .presentation import render_comparison, render_run_list, render_runs
from .runner import (
    PRESET_CONFIGS,
    DeterministicEmbeddingProvider,
    resolve_configs,
    run_matrix,
    seed_fixture_repository,
)
from .store import RunStore, compare_runs
from .suites import load_suite


DEFAULT_RUN_DIRECTORY = Path(".aoms-eval") / "runs"


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """Measure retrieval relevance, safety, packing, and latency."""


@main.command("run")
@click.option("--seed", type=int, default=7, show_default=True)
@click.option("--records", type=click.IntRange(min=78), default=160, show_default=True)
@click.option(
    "--config",
    "config_names",
    type=click.Choice(list(PRESET_CONFIGS)),
    multiple=True,
    default=tuple(PRESET_CONFIGS),
    show_default=True,
    help="Engine config; repeat to run a matrix.",
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    help="Existing SQLite store, always opened read-only; requires --suite.",
)
@click.option(
    "--suite",
    "suite_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    help="QuerySuite JSON (starter suite is used for synthetic runs).",
)
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    help="Optional CorpusManifest JSON for stale/canary metrics.",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=DEFAULT_RUN_DIRECTORY,
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True, help="Print run JSON to stdout.")
def run_command(
    seed: int,
    records: int,
    config_names: tuple[str, ...],
    database: Path | None,
    suite_path: Path | None,
    manifest_path: Path | None,
    output_dir: Path,
    as_json: bool,
) -> None:
    """Run a synthetic fixture or a supplied store across engine configs."""

    if database is not None and suite_path is None:
        raise click.UsageError("--database requires --suite")
    configs = resolve_configs(config_names)
    try:
        runs = asyncio.run(
            _execute_run(
                seed=seed,
                records=records,
                configs=configs,
                database=database,
                suite_path=suite_path,
                manifest_path=manifest_path,
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    store = RunStore(output_dir)
    paths = [store.save(run) for run in runs]
    if as_json:
        click.echo(
            json.dumps(
                [run.model_dump(mode="json") for run in runs],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    click.echo(render_runs(runs))
    click.echo("\nJSON artifacts:")
    for path in paths:
        click.echo(f"  {path}")


async def _execute_run(
    *,
    seed: int,
    records: int,
    configs: list,
    database: Path | None,
    suite_path: Path | None,
    manifest_path: Path | None,
):
    provider = DeterministicEmbeddingProvider()
    if database is not None:
        repository = SQLiteMemoryRepository(database, read_only=True)
        suite = load_suite(suite_path)  # type: ignore[arg-type]
        manifest = (
            CorpusManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            if manifest_path
            else None
        )
        return await run_matrix(
            repository,
            suite,
            configs,
            manifest=manifest,
            embedding_provider=provider,
        )

    corpus = generate_corpus(record_count=records, seed=seed)
    suite = load_suite(suite_path) if suite_path else corpus.suite
    with tempfile.TemporaryDirectory(prefix="aoms-eval-fixture-") as temp_directory:
        repository = await seed_fixture_repository(
            corpus,
            Path(temp_directory) / "fixture.sqlite3",
            embedding_provider=provider,
        )
        return await run_matrix(
            repository,
            suite,
            configs,
            manifest=corpus.manifest,
            corpus_hash=corpus.content_hash,
            embedding_provider=provider,
        )


@main.command("compare")
@click.argument("baseline")
@click.argument("current")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=DEFAULT_RUN_DIRECTORY,
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True)
def compare_command(
    baseline: str, current: str, output_dir: Path, as_json: bool
) -> None:
    """Compare two stored runs by ID, unique prefix, or JSON path."""

    store = RunStore(output_dir)
    try:
        comparison = compare_runs(store.load(baseline), store.load(current))
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(comparison.model_dump_json(indent=2))
        return
    click.echo(
        f"same config: {comparison.same_config}; same suite: {comparison.same_suite}"
    )
    click.echo(render_comparison(comparison))


@main.command("list")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=DEFAULT_RUN_DIRECTORY,
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True)
def list_command(output_dir: Path, as_json: bool) -> None:
    """List stored evaluation runs and their configuration hashes."""

    runs = RunStore(output_dir).list()
    if as_json:
        click.echo(
            json.dumps(
                [run.model_dump(mode="json") for run in runs],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not runs:
        click.echo("No evaluation runs found.")
        return
    click.echo(render_run_list(runs))


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["main"]
