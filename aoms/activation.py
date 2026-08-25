"""Guided host registration and first-run activation helpers."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from importlib import resources
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any, Mapping

from aoms.contracts import RecallResult

# Directory names only. A host's *identity* comes from
# ``aoms.identity.agent_id_for_host``; conflating the two is why the packaged
# Claude hook bound ``claude-code`` while ``setup`` bound ``claude``.
HOST_RECIPE_DIRECTORIES = {
    "claude": "claude-code",
    "codex": "codex",
    "openclaw": "openclaw",
}


@dataclass(frozen=True, slots=True)
class InvocationSource:
    """Reusable command prefix for the package source running setup."""

    command: tuple[str, ...]
    description: str

    @property
    def rendered(self) -> str:
        return shlex.join(self.command)


@dataclass(frozen=True, slots=True)
class ActivationResult:
    server_name: str
    server_version: str
    receipt_id: str
    source_count: int
    empty_visible_store: bool


def _installed_direct_url() -> dict[str, Any] | None:
    try:
        text = distribution("cortex-mem").read_text("direct_url.json")
    except PackageNotFoundError:
        return None
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def detect_invocation_source(
    *,
    direct_url: Mapping[str, Any] | None = None,
    argv0: str | None = None,
    executable: str | None = None,
) -> InvocationSource:
    """Detect a Git-backed uvx environment or preserve the installed launcher."""

    metadata = dict(direct_url) if direct_url is not None else _installed_direct_url()
    vcs = metadata.get("vcs_info") if metadata else None
    url = str(metadata.get("url", "")) if metadata else ""
    if isinstance(vcs, Mapping) and vcs.get("vcs") == "git" and url:
        revision = str(vcs.get("requested_revision") or vcs.get("commit_id") or "")
        git_url = url if url.startswith("git+") else f"git+{url}"
        if revision:
            git_url = f"{git_url}@{revision}"
        return InvocationSource(
            ("uvx", "--from", git_url, "cortex-mem"),
            f"Git source {git_url}",
        )

    launcher = argv0 if argv0 is not None else sys.argv[0]
    python = executable if executable is not None else sys.executable
    if Path(launcher).name == "cortex-mem":
        resolved = str(Path(launcher).expanduser().resolve())
        return InvocationSource((resolved,), f"installed launcher {resolved}")
    return InvocationSource(
        (python, "-m", "aoms.cli"),
        f"installed Python environment {python}",
    )


def host_registration_command(
    host: str,
    source: InvocationSource,
    *,
    agent_id: str,
    workspace: Path,
    data_dir: Path,
) -> tuple[str, ...]:
    """Build the host's exact argv without shell interpolation."""

    environment = {
        "AOMS_AGENT_ID": agent_id,
        "AOMS_WORKSPACE": str(workspace),
        "AOMS_DATA_DIR": str(data_dir),
    }
    server = (*source.command, "mcp")
    if host == "claude":
        return (
            "claude",
            "mcp",
            "add",
            "--scope",
            "local",
            "aoms",
            *(
                part
                for key, value in environment.items()
                for part in ("-e", f"{key}={value}")
            ),
            "--",
            *server,
        )
    if host == "codex":
        return (
            "codex",
            "mcp",
            "add",
            *(
                part
                for key, value in environment.items()
                for part in ("--env", f"{key}={value}")
            ),
            "aoms",
            "--",
            *server,
        )
    if host == "openclaw":
        definition = json.dumps(
            {
                "command": server[0],
                "args": list(server[1:]),
                "env": environment,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return (
            "openclaw",
            "config",
            "set",
            "mcp.servers.aoms",
            definition,
            "--strict-json",
        )
    raise ValueError(f"unsupported host: {host}")


def run_host_registration(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Execute a registration argv and preserve host diagnostics on failure."""

    return subprocess.run(command, check=True, capture_output=True, text=True)


def _copy_resource_tree(source: Any, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            _copy_resource_tree(item, target)
        else:
            target.write_bytes(item.read_bytes())


def _write_bound_launcher(
    destination: Path,
    *,
    source: InvocationSource,
    agent_id: str,
    workspace: Path,
    data_dir: Path,
) -> Path:
    launcher = destination / "cortex-mem-bound"
    lines = [
        "#!/bin/sh",
        f"export AOMS_AGENT_ID={shlex.quote(agent_id)}",
        f"export AOMS_WORKSPACE={shlex.quote(str(workspace))}",
        f"export AOMS_DATA_DIR={shlex.quote(str(data_dir))}",
        f'exec {source.rendered} "$@"',
    ]
    launcher.write_text("\n".join(lines) + "\n", encoding="utf-8")
    launcher.chmod(0o700)
    return launcher


def _bind_recipe_commands(host: str, destination: Path, launcher: Path) -> None:
    """Point lifecycle recipe commands at the source-correct bound launcher."""

    if host == "claude":
        hooks_path = destination / "hooks.json"
        hooks = hooks_path.read_text(encoding="utf-8")
        hooks_path.write_text(
            hooks.replace("cortex-mem recall", f"{shlex.quote(str(launcher))} recall"),
            encoding="utf-8",
        )
    elif host == "codex":
        config_path = destination / "config.toml"
        config_path.write_text(
            "[mcp_servers.aoms]\n"
            f"command = {json.dumps(str(launcher))}\n"
            'args = ["mcp"]\n',
            encoding="utf-8",
        )
    elif host == "openclaw":
        handler_path = destination / "hooks" / "aoms-recall" / "handler.ts"
        handler = handler_path.read_text(encoding="utf-8")
        handler_path.write_text(
            handler.replace(
                '      "cortex-mem",', f"      {json.dumps(str(launcher))},"
            ),
            encoding="utf-8",
        )
        sync_path = destination / "session_sync_v2.py"
        sync = sync_path.read_text(encoding="utf-8")
        sync_path.write_text(
            sync.replace(
                'cortex_mem: str = "cortex-mem"',
                f"cortex_mem: str = {json.dumps(str(launcher))}",
            ),
            encoding="utf-8",
        )


def materialize_host_recipe(
    host: str,
    destination_root: Path,
    *,
    source: InvocationSource,
    agent_id: str,
    workspace: Path,
    data_dir: Path,
) -> Path:
    """Copy the packaged host recipe and record its exact launch binding."""

    recipe_name = HOST_RECIPE_DIRECTORIES[host]
    destination = destination_root / host
    packaged = resources.files("recipes").joinpath(recipe_name)
    _copy_resource_tree(packaged, destination)
    launcher = _write_bound_launcher(
        destination,
        source=source,
        agent_id=agent_id,
        workspace=workspace,
        data_dir=data_dir,
    )
    _bind_recipe_commands(host, destination, launcher)
    binding = {
        "agent_id": agent_id,
        "workspace": str(workspace),
        "data_dir": str(data_dir),
        "source_command": list(source.command),
        "mcp_command": [*source.command, "mcp"],
        "bound_launcher": str(launcher),
    }
    (destination / "aoms-binding.json").write_text(
        json.dumps(binding, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


async def run_activation_check(
    source: InvocationSource,
    *,
    agent_id: str,
    workspace: Path,
    data_dir: Path,
    embedding_environment: Mapping[str, str],
) -> ActivationResult:
    """Handshake with the real stdio server and issue one scoped recall."""

    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    environment = dict(os.environ)
    environment.update(embedding_environment)
    environment.update(
        {
            "AOMS_AGENT_ID": agent_id,
            "AOMS_WORKSPACE": str(workspace),
            "AOMS_DATA_DIR": str(data_dir),
        }
    )
    parameters = StdioServerParameters(
        command=source.command[0],
        args=[*source.command[1:], "mcp"],
        env=environment,
        cwd=workspace,
    )
    with open(os.devnull, "w", encoding="utf-8") as errlog:
        async with stdio_client(parameters, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                if not {"recall", "remember", "search"}.issubset(names):
                    raise RuntimeError(
                        "MCP handshake did not expose the AOMS tool contract"
                    )
                response = await session.call_tool(
                    "recall",
                    {
                        "task": (
                            f"Activation check for {workspace.name}: current durable "
                            "decisions, constraints, failures, and procedures"
                        ),
                        "token_budget": 400,
                    },
                )
                result = RecallResult.model_validate(response.structuredContent)
    receipt_id = str(result.diagnostics.get("receipt_id", ""))
    if not receipt_id:
        raise RuntimeError("activation recall did not return a receipt id")
    return ActivationResult(
        server_name=initialized.serverInfo.name,
        server_version=initialized.serverInfo.version,
        receipt_id=receipt_id,
        source_count=len(result.sources),
        empty_visible_store=bool(result.diagnostics.get("empty_visible_store")),
    )


__all__ = [
    "ActivationResult",
    "InvocationSource",
    "detect_invocation_source",
    "host_registration_command",
    "materialize_host_recipe",
    "run_activation_check",
    "run_host_registration",
]
