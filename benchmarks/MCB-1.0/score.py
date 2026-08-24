#!/usr/bin/env python3
"""Deterministic, adapter-independent scorer for frozen MCB-1.0 results."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent


class ScoreError(ValueError):
    """Raised when cases or result artifacts violate the benchmark contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_freeze(root: Path = ROOT) -> dict[str, Any]:
    manifest = load_json(root / "FREEZE-MANIFEST.json")
    for name, expected in manifest["sha256"].items():
        actual = sha256_file(root / name)
        if actual != expected:
            raise ScoreError(
                f"freeze hash mismatch for {name}: expected {expected}, got {actual}"
            )
    return manifest


def _unit(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != {"topic", "text"}:
        raise ScoreError("state unit must contain exactly string topic and text")
    topic = value["topic"]
    text = value["text"]
    if not isinstance(topic, str) or not topic or not isinstance(text, str) or not text:
        raise ScoreError("state unit topic and text must be non-empty strings")
    return topic, text


def normalize_state(values: Any, *, unique_topics: bool = True) -> set[tuple[str, str]]:
    if not isinstance(values, list):
        raise ScoreError("durable state must be a list")
    units = [_unit(value) for value in values]
    if len(units) != len(set(units)):
        raise ScoreError("durable state contains duplicate statement pairs")
    if unique_topics and len({topic for topic, _ in units}) != len(units):
        raise ScoreError("durable state contains multiple current values for one topic")
    return set(units)


def derive_actual_class(
    initial: set[tuple[str, str]],
    observation: set[tuple[str, str]],
    final: set[tuple[str, str]],
) -> str:
    if final == initial:
        return "preserve" if observation <= initial else "reject"
    observation_topics = {topic for topic, _ in observation}
    for topic in observation_topics:
        values = {text for item_topic, text in final if item_topic == topic}
        if len(values) > 1:
            return "conflict-retained"
    removed = initial - final
    added = final - initial
    if not removed and added:
        return "extend"
    if removed and added:
        added_topics = {topic for topic, _ in added}
        removed_topics = {topic for topic, _ in removed}
        if removed_topics <= added_topics:
            return "revise"
        return "mixed"
    if removed and not added:
        return "erase"
    return "mixed"


def evaluate_case(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    expected = case["expected"]
    initial = normalize_state(case["initial_state"])
    observation = normalize_state(case["observation"]["statements"])
    expected_final = normalize_state(expected["final_state"])
    error = result.get("error")
    structural_error: str | None = None
    try:
        final = normalize_state(result.get("resulting_durable_state"))
        actual_class = derive_actual_class(initial, observation, final)
    except ScoreError as exc:
        final = set()
        actual_class = "invalid"
        structural_error = str(exc)
    passed = (
        error is None
        and structural_error is None
        and final == expected_final
        and actual_class == expected["outcome_class"]
    )
    return {
        "actual_class": actual_class,
        "passed": passed,
        "structural_error": structural_error,
        "final": final,
    }


def _nearest_rank_p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def metrics_for(
    cases: list[dict[str, Any]], results_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    pass_count = 0
    protected_missing = 0
    protected_total = 0
    supersession_valid = 0
    supersession_total = 0
    required_new_missing = 0
    required_new_total = 0
    latencies: list[float] = []

    for case in cases:
        result = results_by_id[case["id"]]
        evaluated = evaluate_case(case, result)
        final = evaluated["final"]
        pass_count += int(evaluated["passed"])
        latencies.append(float(result["latency_ms"]))

        expected = case["expected"]
        protected = normalize_state(expected["protected_state"])
        protected_total += len(protected)
        protected_missing += len(protected - final)

        required_new = normalize_state(expected["required_new_state"])
        if expected["outcome_class"] in {"extend", "revise"}:
            required_new_total += len(required_new)
            required_new_missing += len(required_new - final)

        if expected["outcome_class"] == "revise":
            supersession_total += 1
            obsolete = normalize_state(expected["obsolete_state"])
            expected_final = normalize_state(expected["final_state"])
            valid = (
                result.get("error") is None
                and evaluated["structural_error"] is None
                and not (obsolete & final)
                and required_new <= final
                and protected <= final
                and final == expected_final
            )
            supersession_valid += int(valid)

    return {
        "case_count": len(cases),
        "decision_accuracy": _ratio(pass_count, len(cases)),
        "false_rejection_rate": _ratio(required_new_missing, required_new_total),
        "mean_latency_ms": round(fmean(latencies), 3) if latencies else None,
        "p95_latency_ms": round(_nearest_rank_p95(latencies), 3) if latencies else None,
        "unauthorized_overwrite_rate": _ratio(
            protected_missing, protected_total
        ),
        "valid_supersession_rate": _ratio(
            supersession_valid, supersession_total
        ),
    }


def score_document(corpus: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    cases = corpus["cases"]
    result_rows = document.get("cases")
    if not isinstance(result_rows, list):
        raise ScoreError("results document must contain a cases list")
    results_by_id: dict[str, dict[str, Any]] = {}
    for result in result_rows:
        case_id = result.get("id")
        if not isinstance(case_id, str) or case_id in results_by_id:
            raise ScoreError("result IDs must be unique strings")
        results_by_id[case_id] = result
    expected_ids = [case["id"] for case in cases]
    if set(results_by_id) != set(expected_ids):
        raise ScoreError("result case IDs do not exactly match the frozen corpus")

    per_case: dict[str, dict[str, Any]] = {}
    for case in cases:
        result = results_by_id[case["id"]]
        if result.get("inputs") != {
            "initial_state": case["initial_state"],
            "observation": case["observation"],
        }:
            raise ScoreError(f"input echo mismatch for {case['id']}")
        per_case[case["id"]] = evaluate_case(case, result)

    slices = {"OVERALL": cases}
    slices.update(
        {
            mode: [case for case in cases if case["mode"] == mode]
            for mode in ("INSTRUCTED", "AUTONOMOUS")
        }
    )
    metrics = {
        name: metrics_for(slice_cases, results_by_id)
        for name, slice_cases in slices.items()
    }
    return {
        "metrics": metrics,
        "per_case": {
            case_id: {
                "actual_class": value["actual_class"],
                "passed": value["passed"],
                "structural_error": value["structural_error"],
            }
            for case_id, value in per_case.items()
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--cases", type=Path, default=ROOT / "cases.json")
    parser.add_argument("--skip-freeze-check", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.skip_freeze_check:
        validate_freeze(ROOT)
    corpus = load_json(args.cases)
    document = load_json(args.results)
    print(json.dumps(score_document(corpus, document), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
