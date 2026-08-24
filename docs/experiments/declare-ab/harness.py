"""A/B whether tool-description guidance makes a model declare what it replaces.

Arm A is the surface as shipped at dfc68b6: no mention of supersedes,
claim_key or contesting anywhere, and every parameter a bare type.
Arm B is bb4ee62: the same tools and the same parameters, with guidance.

The two arms differ in nothing else. The model, the seeded store, the task
text, the temperature and the trial order are identical.

Nothing in the task text mentions supersedes, claim_key, contesting, or
updating memory in any particular way. If the prompt had to say it, the
experiment would measure the prompt rather than the surface.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request

OLLAMA = "http://localhost:11434/api/chat"

# Seeded fact the agent should end up correcting.
SEED_TOPIC = "staging-deploy-target"
SEED_TEXT = "The staging environment deploys to Kubernetes cluster cluster-west-2."
SEED_ID = "seed-staging-target"

# Deliberately says nothing about how to write. It describes a situation and
# asks for memory to be right afterwards.
TASK = (
    "We finished migrating staging this morning. Staging no longer deploys to "
    "cluster-west-2; it now deploys to cluster-east-1. Nothing else about "
    "staging changed.\n\n"
    "Make sure AOMS memory is correct for whoever picks this up next session."
)

# Secondary condition: the operator has adopted claim keys (the realistic
# adoption path). It still never mentions supersedes or contesting.
TASK_WITH_SLOTS = (
    TASK
    + "\n\nOur convention: every durable fact carries a claim_key naming the "
    "proposition it answers, so facts about the same thing share one key. "
    "Use the claim_key 'staging-deploy-target' for this."
)


def load_surface(arm_path: str):
    """Import the arm's own contracts so the schema is exactly its own."""
    for name in [m for m in sys.modules if m.startswith("aoms")]:
        del sys.modules[name]
    sys.path.insert(0, arm_path)
    try:
        from aoms.adapters.mcp_server import (  # noqa: PLC0415
            RECALL_DESCRIPTION,
            REMEMBER_DESCRIPTION,
            SEARCH_DESCRIPTION,
        )
        from aoms.contracts import (  # noqa: PLC0415
            RecallRequest,
            RememberRequest,
            SearchRequest,
        )

        tools = []
        for name, model, description in (
            ("recall", RecallRequest, RECALL_DESCRIPTION),
            ("remember", RememberRequest, REMEMBER_DESCRIPTION),
            ("search", SearchRequest, SEARCH_DESCRIPTION),
        ):
            schema = model.model_json_schema()
            schema.pop("additionalProperties", None)
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": schema,
                    },
                }
            )
        return tools
    finally:
        sys.path.remove(arm_path)


async def seed_and_run(arm_path: str, tool_calls: list[dict]) -> dict:
    """Replay the model's tool calls against a real scratch AOMS store."""
    for name in [m for m in sys.modules if m.startswith("aoms")]:
        del sys.modules[name]
    sys.path.insert(0, arm_path)
    from aoms.application import AOMSApplication  # noqa: PLC0415
    from aoms.contracts import (  # noqa: PLC0415
        MemoryKind,
        RecallRequest,
        RememberRequest,
        Scope,
        ScopeContext,
        SearchRequest,
    )
    from aoms.embeddings import NullProvider  # noqa: PLC0415
    from aoms.repositories import SQLiteMemoryRepository  # noqa: PLC0415

    root = pathlib.Path(tempfile.mkdtemp(prefix="decl-", dir="/tmp/decl/stores"))
    repository = SQLiteMemoryRepository(root / "aoms.sqlite3")
    app = AOMSApplication(
        repository,
        scope_context=ScopeContext(agent_id="trial-agent", workspace_id="/trial"),
        embedding_provider=NullProvider(),
        background_embeddings=False,
    )
    await repository.initialize()
    await app.remember(
        RememberRequest(
            id=SEED_ID,
            kind=MemoryKind.FACT,
            content=SEED_TEXT,
            scope=Scope.WORKSPACE,
            claim_key=SEED_TOPIC,
        )
    )

    observed = []
    for call in tool_calls:
        name = call.get("name")
        args = call.get("arguments") or {}
        try:
            if name == "remember":
                args.pop("scope", None)
                result = await app.remember(RememberRequest(**args))
                observed.append(
                    {
                        "tool": "remember",
                        "claim_key": args.get("claim_key"),
                        "supersedes": args.get("supersedes"),
                        "disposition": result.disposition.value,
                        "record_id": result.record.id,
                    }
                )
            elif name == "search":
                await app.search(SearchRequest(**args))
                observed.append({"tool": "search"})
            elif name == "recall":
                await app.recall(RecallRequest(**args))
                observed.append({"tool": "recall"})
        except Exception as exc:  # noqa: BLE001 - a malformed call is data
            observed.append({"tool": name, "error": type(exc).__name__, "detail": str(exc)[:160]})

    connection = sqlite3.connect(root / "aoms.sqlite3")
    connection.row_factory = sqlite3.Row
    contested = connection.execute(
        "SELECT COUNT(*) AS n FROM memories WHERE contested = 1"
    ).fetchone()["n"]
    current = [
        json.loads(r["record_json"])
        for r in connection.execute(
            "SELECT record_json FROM memories WHERE contested = 0"
        ).fetchall()
    ]
    connection.close()
    sys.path.remove(arm_path)
    return {"calls": observed, "contested_records": contested, "current": current}


def ollama_chat(model, messages, tools, temperature, seed):
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        "options": {"temperature": temperature, "seed": seed},
    }
    request = urllib.request.Request(
        OLLAMA,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read())


async def trial(arm_name, arm_path, model, temperature, seed, task_text):
    tools = load_surface(arm_path)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a coding agent with a durable memory service (AOMS) "
                "available as tools. Use the tools when they help. Existing "
                "memory already contains facts from earlier sessions."
            ),
        },
        {"role": "user", "content": task_text},
    ]
    collected = []
    calls_made = 0
    for _ in range(4):  # bounded agent loop
        response = ollama_chat(model, messages, tools, temperature, seed)
        calls_made += 1
        message = response.get("message", {})
        tool_calls = message.get("tool_calls") or []
        messages.append(message)
        if not tool_calls:
            break
        for call in tool_calls:
            function = call.get("function", {})
            name = function.get("name")
            args = function.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            collected.append({"name": name, "arguments": args or {}})
            # Feed back a neutral result so the loop can continue. The seeded
            # record's id is disclosed only through the tools, exactly as it
            # would be in a real session.
            if name in {"recall", "search"}:
                content = json.dumps(
                    {
                        "results": [
                            {
                                "id": SEED_ID,
                                "kind": "fact",
                                "content": SEED_TEXT,
                                "claim_key": SEED_TOPIC,
                            }
                        ]
                    }
                )
            else:
                content = json.dumps({"stored": True})
            messages.append({"role": "tool", "content": content})
    outcome = await seed_and_run(arm_path, collected)
    return {
        "arm": arm_name,
        "seed": seed,
        "model_calls": calls_made,
        "tool_calls": collected,
        **outcome,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--condition", choices=("unprompted", "slots"),
                        default="unprompted")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    pathlib.Path("/tmp/decl/stores").mkdir(parents=True, exist_ok=True)
    task_text = TASK if args.condition == "unprompted" else TASK_WITH_SLOTS
    arms = {"A-no-guidance": "/tmp/decl/armA", "B-guidance": "/tmp/decl/armB"}

    results = []
    total_model_calls = 0
    started = time.perf_counter()
    for index in range(args.trials):
        # Alternate arm order per trial so any drift hits both equally, and
        # give both arms the same seed so they face the same sampling.
        order = list(arms.items())
        if index % 2:
            order.reverse()
        for arm_name, arm_path in order:
            record = await trial(
                arm_name, arm_path, args.model, args.temperature,
                seed=1000 + index, task_text=task_text,
            )
            record["condition"] = args.condition
            results.append(record)
            total_model_calls += record["model_calls"]
        print(f"  trial {index + 1}/{args.trials} done "
              f"({total_model_calls} model calls so far)", flush=True)

    pathlib.Path(args.output).write_text(
        json.dumps(
            {
                "model": args.model,
                "temperature": args.temperature,
                "condition": args.condition,
                "trials_per_arm": args.trials,
                "total_model_calls": total_model_calls,
                "wall_seconds": round(time.perf_counter() - started, 1),
                "results": results,
            },
            indent=2,
        )
    )
    print(f"\nwrote {args.output}; {total_model_calls} model calls")


asyncio.run(main())
