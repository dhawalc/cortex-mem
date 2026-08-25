"""Record every write intent MCB-1.0 puts through the AOMS contest gate.

Replays a frozen MCB-1.0 adapter over the frozen 48-case corpus with a
recording shim wrapped around ``aoms.contest.decide``, and writes one JSON
object per intent to a JSONL trace for ``blindspot`` to fold.

Nothing under the benchmark tree is written or imported for effect other than
the adapter module and the corpus, both read-only. Every scratch store lives
under /tmp, as the adapter itself insists. No model and no network are
involved: the AOMS MCB adapter is a deterministic translation layer.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import aoms.application as application_module
import aoms.contest as contest_module


def _load_adapter(adapter_dir: Path):
    spec = importlib.util.spec_from_file_location(
        f"mcb_adapter_{adapter_dir.name.replace('-', '_')}", adapter_dir / "adapter.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load adapter from {adapter_dir}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_recorder(sink: list[dict[str, object]], reached: list[object]):
    """Record the intent behind every write, and count those reaching the gate.

    The wrap point is ``_adjudicate``, which runs once per write and holds the
    same ``(request, provenance)`` pair the application projects a
    ``WriteIntent`` from. Wrapping ``decide`` instead would silently drop every
    write the ``claim_key is None`` sentinel short-circuits before the gate --
    which for a harness that never sets ``claim_key`` is all of them, and an
    empty trace would understate the denominator rather than name it.

    ``decide`` is wrapped too, on both its bindings (``aoms.application``
    imported it by name), purely to count arrivals.
    """

    original_adjudicate = application_module.AOMSApplication._adjudicate
    original_decide = contest_module.decide

    async def recording_adjudicate(self, request, **kwargs):
        provenance = kwargs["provenance"]
        intent = contest_module.WriteIntent(
            kind=request.kind,
            scope=request.scope,
            content_sha256=contest_module.content_digest(request.content),
            claim_key=request.claim_key,
            supersedes=request.supersedes,
            asserted_at=provenance.asserted_at,
            derived_from=tuple(provenance.derived_from),
        )
        sink.append(json.loads(json.dumps(asdict(intent), default=str)))
        return await original_adjudicate(self, request, **kwargs)

    def recording_decide(intent, slot, **kwargs):
        reached.append(intent)
        return original_decide(intent, slot, **kwargs)

    application_module.AOMSApplication._adjudicate = recording_adjudicate
    contest_module.decide = recording_decide
    application_module.decide = recording_decide
    return original_adjudicate, original_decide


async def _run_case(adapter_module, config: dict, case: dict, run_dir: Path) -> None:
    adapter = adapter_module.create(dict(config, case_id=case["id"]), run_dir)
    try:
        await adapter.establish_durable_state(case["initial_state"])
        adapter.provide_observation(case["observation"])
        await adapter.process()
        await adapter.retrieve_durable_state()
    finally:
        adapter.close()


async def _run_all(adapter_dir: Path, corpus: Path, sink: list) -> int:
    adapter_module = _load_adapter(adapter_dir)
    config = json.loads((adapter_dir / "config.json").read_text(encoding="utf-8"))
    cases = json.loads(corpus.read_text(encoding="utf-8"))["cases"]
    with tempfile.TemporaryDirectory(prefix="blindspot-mcb-", dir="/tmp") as tmp:
        for case in cases:
            run_dir = Path(tmp) / case["id"]
            run_dir.mkdir()
            await _run_case(adapter_module, config, case, run_dir)
    return len(cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blindspot-trace-mcb")
    parser.add_argument("--adapter", required=True, type=Path)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    sink: list[dict[str, object]] = []
    reached: list[object] = []
    original_adjudicate, original_decide = _install_recorder(sink, reached)
    try:
        cases = asyncio.run(_run_all(args.adapter, args.cases, sink))
    finally:
        application_module.AOMSApplication._adjudicate = original_adjudicate
        contest_module.decide = original_decide
        application_module.decide = original_decide

    args.out.write_text(
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in sink),
        encoding="utf-8",
    )
    print(
        f"{args.adapter.name}: {cases} cases, {len(sink)} writes, "
        f"{len(reached)} reached decide() -> {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
