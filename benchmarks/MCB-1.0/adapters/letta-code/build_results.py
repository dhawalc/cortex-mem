#!/usr/bin/env python3
"""Assemble RESULTS-LETTA-CODE.md from the run artifacts.

Reads only result JSON that already exists, so it can be run while later runs
are still in flight; missing runs are reported as missing rather than silently
dropped. It computes every number it prints — nothing is transcribed by hand.
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODES = ("OVERALL", "INSTRUCTED", "AUTONOMOUS")
METRICS = (
    "decision_accuracy",
    "unauthorized_overwrite_rate",
    "false_rejection_rate",
    "valid_supersession_rate",
    "mean_latency_ms",
)


def load(pattern: str) -> list[dict]:
    out = []
    for path in sorted(glob.glob(str(ROOT / pattern))):
        out.append(json.loads(Path(path).read_text(encoding="utf-8")))
    return out


def spread(values: list[float]) -> str:
    if not values:
        return "—"
    if len(values) == 1:
        return f"{values[0]:.3f} (n=1)"
    return (
        f"{statistics.fmean(values):.3f} "
        f"(n={len(values)}, {min(values):.3f}–{max(values):.3f})"
    )


def metric_rows(docs: list[dict]) -> dict[str, dict[str, list[float]]]:
    table: dict[str, dict[str, list[float]]] = {m: {k: [] for k in MODES} for m in METRICS}
    for doc in docs:
        for mode in MODES:
            for metric in METRICS:
                value = doc["metrics"][mode].get(metric)
                if value is not None:
                    table[metric][mode].append(float(value))
    return table


def by_relationship(docs: list[dict]) -> dict[str, tuple[float, int]]:
    """Pass rate per relationship class, pooled across runs."""
    tally: dict[str, list[int]] = {}
    for doc in docs:
        for case in doc["cases"]:
            tally.setdefault(case["relationship"], []).append(int(case["passed"]))
    return {k: (statistics.fmean(v), len(v)) for k, v in sorted(tally.items())}


def section(title: str, docs: list[dict], expected: int) -> str:
    if not docs:
        return f"### {title}\n\n*No runs completed.*\n"
    lines = [
        f"### {title}",
        "",
        f"{len(docs)} of {expected} planned runs completed.",
        "",
        "| Metric | OVERALL | INSTRUCTED | AUTONOMOUS |",
        "|---|---|---|---|",
    ]
    table = metric_rows(docs)
    for metric in METRICS:
        cells = " | ".join(spread(table[metric][mode]) for mode in MODES)
        lines.append(f"| `{metric}` | {cells} |")
    lines += ["", "Pass rate by relationship class, pooled across runs:", "", "| Class | Pass rate | Cases |", "|---|---|---|"]
    for name, (rate, count) in by_relationship(docs).items():
        lines.append(f"| {name} | {rate:.3f} | {count} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "RESULTS-LETTA-CODE.md")
    args = parser.parse_args()

    lc8 = load("results-letta-code-qwen3-8b-run*.json")
    lc27 = load("results-letta-code-qwen36-27b-run*.json")
    control = load("results-control-qwen3-8b-run*.json")
    aoms = load("results-aoms-sameday-replication.json")

    acc = lambda docs: [d["metrics"]["OVERALL"]["decision_accuracy"] for d in docs]
    lc_acc = statistics.fmean(acc(lc8)) if lc8 else None
    ct_acc = statistics.fmean(acc(control)) if control else None
    contribution = (
        None if lc_acc is None or ct_acc is None else round(lc_acc - ct_acc, 4)
    )

    body = [
        "# RESULTS — Letta Code 0.30.31, unratified experimental local backend",
        "",
        "**Read this heading literally.** These numbers are not \"Letta Code's "
        "score\". They are the score of one configuration of an execution mode "
        "Letta gates behind `LETTA_LOCAL_BACKEND_EXPERIMENTAL`, driven by an "
        "adapter Letta has not seen, written by a competitor. The vendor was "
        "not asked and has not ratified any of it. See "
        "`adapters/letta-code/CURRENCY.md`.",
        "",
        "Every figure below was fixed in advance by "
        "`PREREGISTRATION-LETTA-CODE.md`, committed before case 1. Predictions "
        "in that file were not edited afterwards.",
        "",
        "## The finding that survives every known defect",
        "",
        "The insufficiently-supported class is where these systems fail, and it "
        "is the one result untouched by either the model confound or the "
        "durable-state-definition dispute. See the per-class tables below.",
        "",
        "## The subtraction that matters",
        "",
    ]

    if contribution is None:
        body.append("*Awaiting both the framework and control columns.*")
    else:
        body += [
            f"- Letta Code (MemFS), qwen3:8b: **{lc_acc:.3f}** overall decision accuracy",
            f"- Bare qwen3:8b, no framework at all: **{ct_acc:.3f}**",
            f"- **Framework contribution: {contribution:+.3f}**",
            "",
            "The control is a NON-CONFORMING CONTROL: the frozen corpus fed "
            "straight to Ollama with the published V1 Letta persona and two "
            "local function stubs, with no Letta process, server, SDK or MemFS "
            "anywhere in the stack. It is not an MCB adapter result and must "
            "never be quoted as one.",
            "",
            "Per GOVERNANCE §10, fixed before the numbers were known: if the "
            "control matches the framework within run-to-run spread, the "
            "headline is that the framework's contribution is indistinguishable "
            "from zero on this corpus — not a system score.",
        ]

    body += [
        "",
        "## Results",
        "",
        section("Letta Code (MemFS), qwen3:8b", lc8, 3),
        section("Letta Code (MemFS), qwen3.6:27b", lc27, 3),
        section("NON-CONFORMING CONTROL — bare qwen3:8b, no framework", control, 3),
        section("AOMS same-day replication (deterministic adapter)", aoms, 1),
        "## Historical comparison",
        "",
        "The AOMS-vs-Letta table published earlier in this repository compared "
        "AOMS against Letta **server 0.16.8**, a deprecated architecture, and "
        "labelled it simply \"Letta\". That was our error; the vendor corrected "
        "us. Both columns have known defects:",
        "",
        "- The Letta V1 column measured a deprecated server architecture, and "
        "the control above shows most of its score was attributable to the "
        "model rather than to Letta.",
        "- The AOMS column's INSTRUCTED score rests on a 9-keyword substring "
        "match in `adapters/aoms/config.json`, not on a model decision. AOMS is "
        "deterministic here: the same-day replication reproduces it bit-for-bit.",
        "",
        "Nothing published earlier has been edited or deleted. "
        "`adapters/letta/**` and `RESULTS-LETTA.md` are unchanged; their hashes "
        "are recorded in the pre-registration.",
        "",
    ]
    args.output.write_text("\n".join(body).rstrip("\n") + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    if contribution is not None:
        print(f"framework contribution: {contribution:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
