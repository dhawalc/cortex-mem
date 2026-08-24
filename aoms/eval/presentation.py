"""Compact dependency-free terminal rendering for evaluation artifacts."""

from __future__ import annotations

from collections.abc import Sequence

from .models import EvalRun, RunComparison


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    materialized = [list(headers), *[list(row) for row in rows]]
    widths = [max(len(row[index]) for row in materialized) for index in range(len(headers))]
    rendered = []
    for row_index, row in enumerate(materialized):
        rendered.append("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
        if row_index == 0:
            rendered.append("  ".join("-" * width for width in widths))
    return "\n".join(rendered)


def render_runs(runs: Sequence[EvalRun]) -> str:
    rows = []
    for run in runs:
        metric = run.metrics
        rows.append(
            [
                run.engine_config.name,
                str(metric.case_count),
                f"{metric.recall_at_k:.3f}",
                f"{metric.budget_recall:.3f}",
                f"{metric.non_gold_share:.3f}",
                f"{metric.stale_rate:.3f}",
                f"{metric.contradiction_rate:.3f}",
                f"{metric.canary_leakage:.3f}",
                f"{metric.token_utilization:.3f}",
                f"{metric.latency_p95_ms:.2f}",
            ]
        )
    return _table(
        [
            "config",
            "cases",
            "R@k",
            "budget-R",
            "non-gold",
            "stale",
            "contradict",
            "canary",
            "tok-util",
            "p95-ms",
        ],
        rows,
    )


def render_run_list(runs: Sequence[EvalRun]) -> str:
    return _table(
        ["run-id", "created", "config", "config-hash", "suite", "R@k", "budget-R"],
        [
            [
                run.run_id,
                run.created_at.isoformat(timespec="seconds"),
                run.engine_config.name,
                run.config_hash[:12],
                run.suite_name,
                f"{run.metrics.recall_at_k:.3f}",
                f"{run.metrics.budget_recall:.3f}",
            ]
            for run in runs
        ],
    )


def render_comparison(comparison: RunComparison) -> str:
    return _table(
        ["metric", "baseline", "current", "delta"],
        [
            [
                name,
                f"{delta.baseline:.4f}",
                f"{delta.current:.4f}",
                f"{delta.delta:+.4f}",
            ]
            for name, delta in comparison.deltas.items()
        ],
    )


__all__ = ["render_comparison", "render_run_list", "render_runs"]
