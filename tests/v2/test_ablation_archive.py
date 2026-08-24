from __future__ import annotations

import json
from pathlib import Path

from demo.relay.artifacts import validate_bundle

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "demo" / "ablations" / "v2.0.0"


def test_unfiltered_eval_archive_matches_machine_summary() -> None:
    summary = json.loads((ARCHIVE / "summary.json").read_text(encoding="utf-8"))
    artifacts = sorted((ARCHIVE / "eval").glob("*.json"))
    runs = {
        artifact.name: json.loads(artifact.read_text(encoding="utf-8"))
        for artifact in artifacts
    }

    assert summary["status"] == "PASS"
    assert summary["unfiltered"] is True
    assert summary["eval"]["expected_configurations"] == 5
    assert summary["eval"]["artifact_count"] == len(artifacts) == 5
    assert {run["engine_config"]["name"] for run in runs.values()} == {
        "lexical-only",
        "vector-only",
        "hybrid",
        "no-supersession",
        "no-scope",
    }

    metric_names = (
        "recall_at_k",
        "budget_recall",
        "non_gold_share",
        "stale_rate",
        "contradiction_rate",
        "canary_leakage",
        "canary_count",
        "token_utilization",
        "latency_p95_ms",
    )
    for indexed in summary["eval"]["runs"]:
        artifact = Path(indexed["artifact"])
        raw = runs[artifact.name]
        assert indexed["configuration"] == raw["engine_config"]["name"]
        assert indexed["cases"] == raw["metrics"]["case_count"] == len(raw["cases"])
        for metric in metric_names:
            assert indexed[metric] == raw["metrics"][metric]


def test_scripted_relay_ablation_and_archive_manifests_are_complete() -> None:
    summary = json.loads((ARCHIVE / "summary.json").read_text(encoding="utf-8"))
    relay = ARCHIVE / summary["relay"]["bundle"]
    comparison = json.loads((relay / "comparison.json").read_text(encoding="utf-8"))

    assert validate_bundle(relay).valid
    assert validate_bundle(ARCHIVE).valid
    assert comparison["only_variable"] == "MCP memory availability"
    assert comparison["prompts_identical"] is True
    assert comparison["memory_enabled"]["verifier"]["passed"] is True
    assert comparison["memory_disabled"]["verifier"]["passed"] is False
    assert len(comparison["memory_disabled"]["verifier"]["failures"]) == 3
