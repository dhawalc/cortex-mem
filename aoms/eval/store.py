"""Persistent run artifacts and regression comparisons."""

from __future__ import annotations

from pathlib import Path

from .models import EvalRun, MetricDelta, RunComparison


COMPARABLE_METRICS = (
    "recall_at_k",
    "budget_recall",
    "non_gold_share",
    "stale_rate",
    "contradiction_rate",
    "canary_leakage",
    "token_utilization",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
)


class RunStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def save(self, run: EvalRun) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{run.run_id}.json"
        path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, identifier: str | Path) -> EvalRun:
        supplied = Path(identifier)
        if supplied.is_file():
            return EvalRun.model_validate_json(supplied.read_text(encoding="utf-8"))
        exact = self.directory / f"{identifier}.json"
        if exact.is_file():
            return EvalRun.model_validate_json(exact.read_text(encoding="utf-8"))
        matches = sorted(self.directory.glob(f"{identifier}*.json"))
        if not matches:
            raise FileNotFoundError(f"evaluation run not found: {identifier}")
        if len(matches) > 1:
            raise ValueError(f"run prefix is ambiguous: {identifier}")
        return EvalRun.model_validate_json(matches[0].read_text(encoding="utf-8"))

    def list(self) -> list[EvalRun]:
        if not self.directory.is_dir():
            return []
        runs = [
            EvalRun.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self.directory.glob("*.json")
        ]
        return sorted(runs, key=lambda run: (run.created_at, run.run_id), reverse=True)


def compare_runs(baseline: EvalRun, current: EvalRun) -> RunComparison:
    deltas: dict[str, MetricDelta] = {}
    for name in COMPARABLE_METRICS:
        before = float(getattr(baseline.metrics, name))
        after = float(getattr(current.metrics, name))
        deltas[name] = MetricDelta(
            baseline=before,
            current=after,
            delta=after - before,
        )
    return RunComparison(
        baseline_run_id=baseline.run_id,
        current_run_id=current.run_id,
        same_config=baseline.config_hash == current.config_hash,
        same_suite=baseline.suite_hash == current.suite_hash,
        deltas=deltas,
    )


__all__ = ["COMPARABLE_METRICS", "RunStore", "compare_runs"]
