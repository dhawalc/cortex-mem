#!/usr/bin/env python3
"""Run off-corpus pilot cases through the letta-code adapter.

Pilots never touch the frozen corpus. They exist to prove mechanics (a memory
tool call happens, TOPIC :: TEXT survives, nothing truncates) and to observe the
AUTONOMOUS stance before any frozen case runs. Output is a JSON transcript; no
scoring is performed here.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_adapter():
    spec = importlib.util.spec_from_file_location("mcb_pilot_adapter", HERE / "adapter.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["mcb_pilot_adapter"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--config", default=HERE / "config.json", type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    adapter = _load_adapter()
    base_config = json.loads(args.config.read_text(encoding="utf-8"))
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    args.run_dir.mkdir(parents=True, exist_ok=False)

    rows = []
    for case in cases:
        case_dir = args.run_dir / case["id"]
        case_dir.mkdir()
        instance = adapter.create({**base_config, "case_id": case["id"]}, case_dir)
        started = time.perf_counter_ns()
        error = None
        state = []
        try:
            instance.establish_durable_state(case["initial_state"])
            instance.provide_observation(case["observation"])
            instance.process()
            state = instance.retrieve_durable_state()
        except Exception as exc:  # pilots record failures rather than hiding them
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = round((time.perf_counter_ns() - started) / 1_000_000, 3)
        instance.close()
        transcript = json.loads(
            (case_dir / "letta-code-transcript.json").read_text(encoding="utf-8")
        )
        wrote = [
            entry
            for entry in transcript
            if entry["event"] == "memory_settled"
        ]
        rows.append(
            {
                "id": case["id"],
                "note": case.get("note"),
                "initial_state": case["initial_state"],
                "observation": case["observation"],
                "resulting_durable_state": state,
                "error": error,
                "latency_ms": latency_ms,
                "commit_log_after": wrote[-1]["log"] if wrote else None,
                "agent_id": instance.agent_id,
            }
        )
        print(json.dumps(rows[-1], indent=2))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"pilot_cases": rows}, indent=2) + "\n", encoding="utf-8")
    print(f"pilot result: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
