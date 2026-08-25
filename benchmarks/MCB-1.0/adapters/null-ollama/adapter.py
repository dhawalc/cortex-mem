#!/usr/bin/env python3
"""NON-CONFORMING CONTROL -- a model measurement, NOT an MCB-1.0 adapter result.

THIS IS NOT A MEMORY SYSTEM. It must never appear as a competitor row.

This harness deliberately removes the memory framework from the stack. It feeds
the frozen MCB-1.0 corpus straight to Ollama's /api/chat using the *published
Letta V1 adapter's own persona, separator and preamble* -- read verbatim from
the config file named by ``persona_source`` in this directory's ``config.json``,
which points at ``adapters/letta/config.json`` -- plus two local function stubs
that stand in for ``memory_insert`` / ``memory_replace``. The durable block is a
Python string in this process. No Letta process, server, SDK or MemFS is
involved anywhere, and no memory system of any kind is under test.

It exists to answer one question: how much of a framework's MCB score is the
framework, and how much is the underlying model? The framework's contribution is
(framework score - control score). A control that matches the framework within
run-to-run spread means the framework's measured contribution is indistinguishable
from zero on this corpus.

Because there is no system under test in the MCB sense, this output MUST NOT be
published in the same table as conforming adapter results without the
NON-CONFORMING CONTROL label. This file is deliberately NOT runner-compatible:
it defines ``create`` only so that ``runner.py`` refuses it with an explanatory
error instead of an opaque one. See ``create`` at the bottom of this file.

Scoring uses the frozen score.py unchanged, and the freeze is verified before
any case runs. Run it directly, from the MCB-1.0 directory:

    python adapters/null-ollama/adapter.py \\
        --model qwen3:8b --output results-null-ollama-qwen3-8b.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_score():
    spec = importlib.util.spec_from_file_location("mcb_control_score", ROOT / "score.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["mcb_control_score"] = module
    spec.loader.exec_module(module)
    return module


SCORE = _load_score()
HERE = Path(__file__).resolve().parent
CONTROL_CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))

# The persona, separator and statement preamble are NOT authored here. They are
# read verbatim out of the published adapter this control is the control for, so
# that the only difference between the two stacks is the framework itself.
PERSONA_SOURCE = CONTROL_CFG["persona_source"]
CFG = json.loads((ROOT / PERSONA_SOURCE).read_text(encoding="utf-8"))
PERSONA = CFG["persona"]
SEP = CFG["separator"]
PREAMBLE = CFG["statement_preamble"]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory_insert",
            "description": "Add one line to the facts block.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "new_string": {"type": "string", "description": "TOPIC :: STATEMENT"},
                },
                "required": ["label", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_replace",
            "description": (
                "Rewrite an existing line character for character; empty "
                "new_string deletes it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["label", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Send one short sentence to the user. Ends your turn.",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        },
    },
]


def chat(url: str, model: str, messages: list[dict], num_ctx: int, timeout: int = 900):
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "tools": TOOLS,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": num_ctx},
        }
    ).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def parse_block(value: str) -> list[dict[str, str]]:
    pairs: list[tuple[str, str]] = []
    unparsed = 0
    for raw in value.splitlines():
        line = raw.strip()
        if not line:
            continue
        if SEP in line:
            topic, text = line.split(SEP, 1)
            pairs.append((topic.strip(), text.strip()))
        else:
            unparsed += 1
            pairs.append((f"<unparsed-{unparsed}>", line))
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for topic, text in pairs:
        if (topic, text) in seen:
            continue
        seen.add((topic, text))
        out.append({"topic": topic, "text": text})
    return out


def _system(block: str) -> str:
    return PERSONA + '\n\nThe "facts" block currently contains:\n<facts>\n' + block + "\n</facts>"


def run_case(url: str, model: str, case: dict, num_ctx: int, max_steps: int = 8):
    block = "\n".join(f"{u['topic']}{SEP}{u['text']}" for u in case["initial_state"])
    observation = case["observation"]
    lines = "\n".join(f"{u['topic']}{SEP}{u['text']}" for u in observation["statements"])
    user = f"{observation['text']}\n\n{PREAMBLE}\n{lines}"
    messages = [
        {"role": "system", "content": _system(block)},
        {"role": "user", "content": user},
    ]
    calls: list[dict] = []
    started = time.perf_counter_ns()
    for _ in range(max_steps):
        try:
            response = chat(url, model, messages, num_ctx)
        except Exception as exc:
            elapsed = (time.perf_counter_ns() - started) / 1e6
            return block, calls, f"{type(exc).__name__}: {exc}", elapsed
        message = response.get("message", {})
        tool_calls = message.get("tool_calls") or []
        messages.append(
            {
                "role": "assistant",
                "content": message.get("content", ""),
                **({"tool_calls": tool_calls} if tool_calls else {}),
            }
        )
        if not tool_calls:
            break
        done = False
        for call in tool_calls:
            function = call.get("function", {})
            name = function.get("name")
            args = function.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            calls.append({"name": name, "args": args})
            result = "ok"
            if name == "memory_insert":
                new = (args.get("new_string") or "").strip()
                if new:
                    block = (block + "\n" + new).strip("\n")
            elif name == "memory_replace":
                old = (args.get("old_string") or "").strip()
                new = (args.get("new_string") or "").strip()
                existing = block.splitlines()
                if old in [line.strip() for line in existing]:
                    rebuilt = []
                    for line in existing:
                        if line.strip() == old:
                            if new:
                                rebuilt.append(new)
                        else:
                            rebuilt.append(line)
                    block = "\n".join(rebuilt)
                else:
                    result = "error: old_string not found verbatim"
            elif name == "send_message":
                done = True
            else:
                result = "error: unknown tool"
            messages.append(
                {
                    "role": "tool",
                    "content": result,
                    **({"tool_name": name} if name else {}),
                }
            )
        if done:
            break
        messages[0]["content"] = _system(block)
    return block, calls, None, (time.perf_counter_ns() - started) / 1e6


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=CONTROL_CFG["model"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ollama-url", default=CONTROL_CFG["ollama_url"])
    parser.add_argument("--num-ctx", type=int, default=CONTROL_CFG["num_ctx"])
    parser.add_argument("--max-steps", type=int, default=CONTROL_CFG["max_steps"])
    args = parser.parse_args()

    manifest = SCORE.validate_freeze(ROOT)
    corpus = SCORE.load_json(ROOT / "cases.json")
    cases = corpus["cases"]

    rows = []
    for index, case in enumerate(cases, 1):
        block, calls, error, latency_ms = run_case(
            args.ollama_url, args.model, case, args.num_ctx, args.max_steps
        )
        rows.append(
            {
                "actual_class": None,
                "error": error,
                "expected_class": case["expected"]["outcome_class"],
                "id": case["id"],
                # score.py requires every result row to echo the case inputs
                # verbatim, so a result document cannot be silently detached
                # from the corpus it claims to answer. Without this the frozen
                # scorer refuses the document with "input echo mismatch".
                "inputs": {
                    "initial_state": case["initial_state"],
                    "observation": case["observation"],
                },
                "latency_ms": round(latency_ms, 3),
                "mode": case["mode"],
                "passed": False,
                "relationship": case["relationship"],
                "resulting_durable_state": parse_block(block),
                "structural_error": None,
                "tool_calls": calls,
                "final_block": block,
            }
        )
        print(
            f"[{index:2}/{len(cases)}] {case['id']:10} "
            f"{latency_ms / 1000:7.1f}s {'ERR' if error else ''}",
            flush=True,
        )

    scored = SCORE.score_document(corpus, {"cases": rows})
    for row in rows:
        verdict = scored["per_case"][row["id"]]
        row["actual_class"] = verdict["actual_class"]
        row["passed"] = verdict["passed"]
        row["structural_error"] = verdict["structural_error"]

    document = {
        "adapter": {
            "name": "NON-CONFORMING CONTROL: bare model, no memory framework",
            "system": f"Ollama {args.model} via /api/chat, num_ctx={args.num_ctx}",
            "warning": (
                "This is not an MCB-1.0 adapter result and not a memory system. "
                "No framework is under test. Publish only under the "
                "NON-CONFORMING CONTROL label, never as a competitor row."
            ),
            "persona_source": f"{PERSONA_SOURCE} (verbatim)",
            "max_steps": args.max_steps,
            "version": "MCB-1.0-null-ollama-control-1",
        },
        "benchmark": "MCB-1.0",
        "cases": rows,
        "conforming": False,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "freeze": manifest,
        "metrics": scored["metrics"],
        "schema_version": 1,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(scored["metrics"], indent=2, sort_keys=True))
    print(f"control result: {args.output}")
    return 0


def create(config, run_dir):  # noqa: ARG001 - deliberately refuses
    """Refuse to be driven by runner.py, loudly and with the reason.

    ``runner.py`` accepts an adapter module by checking that it exposes a
    callable ``create(config, run_dir)``. This control is not an adapter: it has
    no durable store to establish, nothing to retrieve, and no system under
    test. Rather than let it be loaded and produce a result document that would
    sit alongside conforming adapters in the results directory, it fails here.
    """
    raise RuntimeError(
        "null-ollama is a NON-CONFORMING CONTROL, not an MCB-1.0 adapter. It "
        "measures a bare language model with no memory system in the stack, "
        "and must never be scored through runner.py or placed in a comparison "
        "table. Run it directly: "
        "python adapters/null-ollama/adapter.py --output <path>"
    )


if __name__ == "__main__":
    raise SystemExit(main())
