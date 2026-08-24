#!/usr/bin/env python3
"""Execute frozen MCB-1.0 cases through a framework-specific adapter."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import inspect
import json
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Python module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SCORE = _load_module(ROOT / "score.py", "mcb_1_0_score")


async def _call(instance: object, method: str, *args: Any) -> Any:
    function = getattr(instance, method)
    value = function(*args)
    return await value if inspect.isawaitable(value) else value


async def _run_case(
    adapter_module: ModuleType,
    base_config: dict[str, Any],
    run_dir: Path,
    case: dict[str, Any],
) -> dict[str, Any]:
    case_dir = run_dir / case["id"]
    case_dir.mkdir(parents=False, exist_ok=False)
    config = {**base_config, "case_id": case["id"]}
    instance = adapter_module.create(config, case_dir)
    if inspect.isawaitable(instance):
        instance = await instance
    durable_state: Any = []
    error: str | None = None
    started = time.perf_counter_ns()
    try:
        await _call(instance, "establish_durable_state", case["initial_state"])
        await _call(instance, "provide_observation", case["observation"])
        await _call(instance, "process")
        durable_state = await _call(instance, "retrieve_durable_state")
    except Exception as exc:  # result artifacts retain adapter failures
        error = f"{type(exc).__name__}: {exc}"
        try:
            durable_state = await _call(instance, "retrieve_durable_state")
        except Exception as retrieve_exc:
            error += (
                f"; retrieval failed with {type(retrieve_exc).__name__}: "
                f"{retrieve_exc}"
            )
            durable_state = []
    latency_ms = round((time.perf_counter_ns() - started) / 1_000_000, 3)
    close = getattr(instance, "close", None)
    if close is not None:
        try:
            value = close()
            if inspect.isawaitable(value):
                await value
        except Exception as exc:
            suffix = f"close failed with {type(exc).__name__}: {exc}"
            error = f"{error}; {suffix}" if error else suffix
    return {
        "actual_class": None,
        "error": error,
        "expected_class": case["expected"]["outcome_class"],
        "id": case["id"],
        "inputs": {
            "initial_state": case["initial_state"],
            "observation": case["observation"],
        },
        "latency_ms": latency_ms,
        "mode": case["mode"],
        "passed": False,
        "relationship": case["relationship"],
        "resulting_durable_state": durable_state,
        "structural_error": None,
    }


async def _run_all(
    adapter_module: ModuleType,
    config: dict[str, Any],
    run_dir: Path,
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        rows.append(await _run_case(adapter_module, config, run_dir, case))
    return rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run-dir", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = SCORE.validate_freeze(ROOT)
    corpus = SCORE.load_json(ROOT / "cases.json")
    adapter_path = args.adapter.resolve()
    adapter_module = _load_module(adapter_path, "mcb_external_adapter")
    if not callable(getattr(adapter_module, "create", None)):
        raise RuntimeError("adapter module must expose callable create(config, run_dir)")
    config = SCORE.load_json(args.config) if args.config else {}
    if not isinstance(config, dict):
        raise RuntimeError("adapter config must be a JSON object")
    if args.run_dir:
        run_dir = args.run_dir.resolve()
        run_dir.mkdir(parents=True, exist_ok=False)
    else:
        run_dir = Path(tempfile.mkdtemp(prefix="mcb-1.0-"))

    rows = asyncio.run(
        _run_all(adapter_module, config, run_dir, corpus["cases"])
    )
    draft = {"cases": rows}
    scored = SCORE.score_document(corpus, draft)
    for row in rows:
        verdict = scored["per_case"][row["id"]]
        row["actual_class"] = verdict["actual_class"]
        row["passed"] = verdict["passed"]
        row["structural_error"] = verdict["structural_error"]

    document = {
        "adapter": getattr(
            adapter_module,
            "ADAPTER_INFO",
            {"name": adapter_path.stem, "module": str(adapter_path)},
        ),
        "benchmark": "MCB-1.0",
        "cases": rows,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        },
        "freeze": manifest,
        "metrics": scored["metrics"],
        "run_storage": str(run_dir),
        "schema_version": 1,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(scored["metrics"], indent=2, sort_keys=True))
    print(f"result: {args.output}")
    print(f"scratch storage: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
