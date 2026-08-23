from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from aoms.eval.cli import main
from aoms.eval.corpus import generate_corpus
from aoms.eval.models import QuerySuite
from aoms.eval.presentation import render_comparison
from aoms.eval.runner import PRESET_CONFIGS, run_matrix, seed_fixture_repository
from aoms.eval.store import RunStore, compare_runs
from aoms.repositories.sqlite import SQLiteMemoryRepository


@pytest.mark.asyncio
async def test_full_mini_eval_run_and_engine_matrix(tmp_path: Path) -> None:
    corpus = generate_corpus(record_count=78, seed=11)
    repository = await seed_fixture_repository(corpus, tmp_path / "fixture.sqlite3")
    mini_suite = QuerySuite(
        name="mini-all-categories",
        version="1",
        cases=[corpus.suite.cases[index] for index in range(6)],
    )

    runs = await run_matrix(
        repository,
        mini_suite,
        list(PRESET_CONFIGS.values()),
        manifest=corpus.manifest,
        corpus_hash=corpus.content_hash,
    )

    assert [run.engine_config.name for run in runs] == list(PRESET_CONFIGS)
    assert all(run.metrics.case_count == 6 for run in runs)
    assert all(len(run.cases) == 6 for run in runs)
    assert all(run.config_hash == run.engine_config.config_hash for run in runs)
    assert next(run for run in runs if run.engine_config.name == "hybrid").corpus_hash
    assert next(
        run for run in runs if run.engine_config.name == "no-scope"
    ).metrics.canary_count > 0
    assert next(
        run for run in runs if run.engine_config.name == "hybrid"
    ).metrics.canary_count == 0


@pytest.mark.asyncio
async def test_existing_store_eval_is_read_only_and_receipts_stay_in_memory(
    tmp_path: Path,
) -> None:
    corpus = generate_corpus(record_count=78, seed=12)
    database = tmp_path / "read-only-fixture.sqlite3"
    writable = await seed_fixture_repository(corpus, database)
    read_only = SQLiteMemoryRepository(database, read_only=True)
    one_case = QuerySuite(
        name="read-only-mini", version="1", cases=[corpus.suite.cases[0]]
    )

    runs = await run_matrix(
        read_only,
        one_case,
        [PRESET_CONFIGS["lexical-only"]],
        manifest=corpus.manifest,
        corpus_hash=corpus.content_hash,
    )

    assert runs[0].environment["repository_read_only"] is True
    assert await writable.recent_recall_receipts(limit=10) == []


def test_cli_run_list_and_comparison_output(tmp_path: Path) -> None:
    runner = CliRunner()
    output_dir = tmp_path / "runs"
    result = runner.invoke(
        main,
        [
            "run",
            "--records",
            "78",
            "--seed",
            "13",
            "--config",
            "lexical-only",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "budget-R" in result.output
    assert "JSON artifacts:" in result.output
    runs = RunStore(output_dir).list()
    assert len(runs) == 1
    assert len(runs[0].cases) == 36

    listed = runner.invoke(main, ["list", "--output-dir", str(output_dir)])
    assert listed.exit_code == 0
    assert runs[0].config_hash[:12] in listed.output

    comparison = compare_runs(runs[0], runs[0])
    rendered = render_comparison(comparison)
    assert "recall_at_k" in rendered
    assert "+0.0000" in rendered
    compared = runner.invoke(
        main,
        [
            "compare",
            runs[0].run_id,
            runs[0].run_id,
            "--output-dir",
            str(output_dir),
        ],
    )
    assert compared.exit_code == 0
    assert "same config: True; same suite: True" in compared.output
