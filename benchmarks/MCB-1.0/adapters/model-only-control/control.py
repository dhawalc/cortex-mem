#!/usr/bin/env python3
"""NON-CONFORMING CONTROL -- a model measurement, NOT an MCB-1.0 adapter result.

This harness deliberately removes the memory framework from the stack. It feeds
the frozen MCB-1.0 corpus straight to Ollama's /api/chat using the *published
Letta V1 adapter's own persona, separator and preamble* (read verbatim from
``adapters/letta/config.json``) plus two local function stubs that stand in for
``memory_insert`` / ``memory_replace``. The block lives in a Python string. No
Letta process, server, SDK or MemFS is involved anywhere.

It exists to answer one question: how much of a framework's MCB score is the
framework, and how much is the underlying model? The framework's contribution is
(framework score - control score). A control that matches the framework within
run-to-run spread means the framework's measured contribution is indistinguishable
from zero on this corpus.

Because there is no system under test in the MCB sense, this output MUST NOT be
published in the same table as conforming adapter results without the
NON-CONFORMING CONTROL label, and it is never written through runner.py.

Scoring uses the frozen score.py unchanged, and the freeze is verified here.
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
CFG = json.loads((ROOT / "adapters/letta/config.json").read_text(encoding="utf-8"))
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
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--num-ctx", type=int, default=8192)
    args = parser.parse_args()

    manifest = SCORE.validate_freeze(ROOT)
    corpus = SCORE.load_json(ROOT / "cases.json")
    cases = corpus["cases"]

    rows = []
    for index, case in enumerate(cases, 1):
        block, calls, error, latency_ms = run_case(
            args.ollama_url, args.model, case, args.num_ctx
        )
        rows.append(
            {
                "actual_class": None,
                "error": error,
                "expected_class": case["expected"]["outcome_class"],
                "id": case["id"],
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
                "This is not an MCB-1.0 adapter result. No framework is under "
                "test. Publish only under the NON-CONFORMING CONTROL label."
            ),
            "persona_source": "adapters/letta/config.json (verbatim)",
            "version": "MCB-1.0-model-only-control-1",
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


if __name__ == "__main__":
    raise SystemExit(main())
