"""Deterministic fake agent that executes YAML-declared MCP and repo tool calls."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _safe_target(workdir: Path, relative: str) -> Path:
    target = (workdir / relative).resolve()
    try:
        target.relative_to(workdir.resolve())
    except ValueError as exc:
        raise ValueError(f"script path escapes working directory: {relative}") from exc
    return target


def _run_git(workdir: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


async def _execute(
    *,
    script_path: Path,
    stage: str,
    workdir: Path,
    prompt: str,
    session_id: str,
    mcp_config_path: Path | None,
) -> dict[str, Any]:
    script = yaml.safe_load(script_path.read_text(encoding="utf-8"))
    actions = script["stages"][stage]["calls"]
    memory_enabled = mcp_config_path is not None
    results: list[dict[str, Any]] = []

    async def run_actions(session: ClientSession | None) -> None:
        for index, action in enumerate(actions, 1):
            condition = action.get("when_memory", "always")
            if condition == "enabled" and not memory_enabled:
                continue
            if condition == "disabled" and memory_enabled:
                continue
            tool = action["tool"]
            record: dict[str, Any] = {"index": index, "tool": tool}
            if tool == "mcp.call":
                if session is None:
                    record.update({"status": "memory-disabled", "result": None})
                else:
                    response = await session.call_tool(
                        action["name"], action.get("arguments", {})
                    )
                    record.update(
                        {
                            "status": "ok" if not response.isError else "error",
                            "result": response.structuredContent,
                        }
                    )
                    if response.isError and action.get("required", True):
                        raise RuntimeError(f"MCP tool failed: {action['name']}")
            elif tool == "file.write":
                target = _safe_target(workdir, action["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(action["content"], encoding="utf-8")
                record.update({"status": "ok", "path": action["path"]})
            elif tool == "git.commit":
                _run_git(workdir, "add", "-A")
                status = _run_git(workdir, "status", "--porcelain")
                if status:
                    _run_git(workdir, "commit", "-m", action["message"])
                    record.update(
                        {"status": "ok", "commit": _run_git(workdir, "rev-parse", "HEAD")}
                    )
                else:
                    record.update({"status": "no-changes"})
            else:
                raise ValueError(f"unknown scripted tool: {tool}")
            results.append(record)

    if mcp_config_path is None:
        await run_actions(None)
    else:
        payload = json.loads(mcp_config_path.read_text(encoding="utf-8"))
        server = payload["mcpServers"]["aoms"]
        parameters = StdioServerParameters(
            command=server["command"],
            args=server.get("args", []),
            env=server.get("env", {}),
            cwd=workdir,
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await run_actions(session)

    return {
        "schema_version": 1,
        "stage": stage,
        "session_id": session_id,
        "prompt": prompt,
        "memory_enabled": memory_enabled,
        "calls": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--workdir", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--mcp-config", type=Path)
    args = parser.parse_args(argv)
    result = asyncio.run(
        _execute(
            script_path=args.script,
            stage=args.stage,
            workdir=args.workdir,
            prompt=args.prompt_file.read_text(encoding="utf-8"),
            session_id=args.session_id,
            mcp_config_path=args.mcp_config,
        )
    )
    args.result.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"stage": args.stage, "calls": len(result["calls"])}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
