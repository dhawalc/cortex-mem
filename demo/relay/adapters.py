"""Fresh-process adapters for relay-compatible agent clients."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdapterUnavailable(RuntimeError):
    """The requested client has no usable headless adapter yet."""


@dataclass(frozen=True, slots=True)
class AdapterRequest:
    stage: str
    prompt: str
    prompt_path: Path
    workdir: Path
    stdout_path: Path
    stderr_path: Path
    result_path: Path
    mcp_config_path: Path | None
    script_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ProcessResult:
    adapter: str
    argv: tuple[str, ...]
    pid: int
    returncode: int
    started_at: str
    ended_at: str
    wall_time_seconds: float
    fresh_session_id: str
    adapter_evidence: dict[str, object] = field(default_factory=dict)

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


class AgentAdapter(Protocol):
    """A client that starts one new, non-resumable process per request."""

    name: str

    def build_command(self, request: AdapterRequest, session_id: str) -> list[str]: ...

    def version(self) -> str: ...


def _executable_version(executable: str, *arguments: str) -> str:
    resolved = shutil.which(executable)
    if resolved is None:
        return "not-installed"
    try:
        completed = subprocess.run(
            [resolved, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unavailable: {exc}"
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return output[0] if output else f"exit-{completed.returncode}"


class ClaudeAdapter:
    """Claude Code print-mode adapter with only the injected MCP configuration."""

    name = "claude"

    def build_command(self, request: AdapterRequest, session_id: str) -> list[str]:
        if request.mcp_config_path is None:
            mcp_arguments: list[str] = []
        else:
            mcp_arguments = [
                "--mcp-config",
                str(request.mcp_config_path),
                "--strict-mcp-config",
            ]
        return [
            "claude",
            "-p",
            request.prompt,
            "--bare",
            "--disable-slash-commands",
            "--no-chrome",
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--session-id",
            session_id,
            "--permission-mode",
            "acceptEdits",
            *mcp_arguments,
        ]

    def version(self) -> str:
        return _executable_version("claude", "--version")


def _toml_string(value: str) -> str:
    # JSON string quoting is also valid TOML basic-string quoting.
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: list[str]) -> str:
    return "[" + ",".join(_toml_string(value) for value in values) + "]"


def _toml_inline_table(values: dict[str, str]) -> str:
    pairs = (
        f"{key}={_toml_string(value)}" for key, value in sorted(values.items())
    )
    return "{" + ",".join(pairs) + "}"


class CodexAdapter:
    """Codex non-interactive adapter using ephemeral session storage."""

    name = "codex"

    def build_command(self, request: AdapterRequest, session_id: str) -> list[str]:
        del session_id  # Codex proves freshness with --ephemeral, not a chosen ID.
        command = [
            "codex",
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "-C",
            str(request.workdir),
            "-s",
            "workspace-write",
            "-a",
            "never",
        ]
        if request.mcp_config_path is not None:
            payload = json.loads(request.mcp_config_path.read_text(encoding="utf-8"))
            server = payload["mcpServers"]["aoms"]
            command.extend(
                [
                    "-c",
                    "mcp_servers.aoms.command=" + _toml_string(server["command"]),
                    "-c",
                    "mcp_servers.aoms.args=" + _toml_array(server.get("args", [])),
                    "-c",
                    "mcp_servers.aoms.env=" + _toml_inline_table(server.get("env", {})),
                ]
            )
        command.append(request.prompt)
        return command

    def version(self) -> str:
        return _executable_version("codex", "--version")


class ScriptedAdapter:
    """Deterministic subprocess adapter driven by fixture YAML tool calls."""

    name = "scripted"

    def build_command(self, request: AdapterRequest, session_id: str) -> list[str]:
        if request.script_path is None:
            raise ValueError("scripted adapter requires a YAML script")
        command = [
            sys.executable,
            "-m",
            "demo.relay.scripted_agent",
            "--script",
            str(request.script_path),
            "--stage",
            request.stage,
            "--prompt-file",
            str(request.prompt_path),
            "--workdir",
            str(request.workdir),
            "--result",
            str(request.result_path),
            "--session-id",
            session_id,
        ]
        if request.mcp_config_path is not None:
            command.extend(["--mcp-config", str(request.mcp_config_path)])
        return command

    def version(self) -> str:
        return "scripted-adapter/1"


class OpenClawAdapter:
    """OpenClaw embedded one-shot adapter with private config and state."""

    name = "openclaw"
    _model_environment_key = "AOMS_RELAY_OPENCLAW_MODEL"

    @staticmethod
    def _config_path(request: AdapterRequest) -> Path:
        return request.result_path.parent / "openclaw-config.json"

    @staticmethod
    def _state_path(request: AdapterRequest) -> Path:
        return request.result_path.parent / "openclaw-state"

    def _write_private_config(self, request: AdapterRequest) -> Path:
        config: dict[str, object] = {
            "agents": {
                "defaults": {
                    "skipBootstrap": True,
                    "workspace": str(request.workdir),
                }
            },
            "tools": {"profile": "coding"},
        }
        if request.mcp_config_path is not None:
            payload = json.loads(
                request.mcp_config_path.read_text(encoding="utf-8")
            )
            source_server = payload["mcpServers"]["aoms"]
            server = dict(source_server)
            transport = server.pop("type", "stdio")
            if transport != "stdio":
                raise ValueError(
                    "OpenClaw relay adapter currently requires a stdio MCP server"
                )
            config["mcp"] = {"servers": {"aoms": server}}

        config_path = self._config_path(request)
        config_path.write_text(
            json.dumps(config, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return config_path

    def build_command(self, request: AdapterRequest, session_id: str) -> list[str]:
        state_path = self._state_path(request)
        if state_path.exists():
            raise AdapterUnavailable(
                "OpenClaw private state path already exists; refusing to claim a "
                f"fresh context: {state_path}"
            )
        self._write_private_config(request)
        command = [
            "openclaw",
            "agent",
            "--local",
            "--agent",
            "main",
            "--session-id",
            session_id,
        ]
        model = os.environ.get(self._model_environment_key, "").strip()
        if model:
            command.extend(["--model", model])
        command.extend(["--message", request.prompt, "--json"])
        return command

    def environment(self, request: AdapterRequest) -> dict[str, str]:
        return {
            "OPENCLAW_CONFIG_PATH": str(self._config_path(request)),
            "OPENCLAW_STATE_DIR": str(self._state_path(request)),
        }

    def capture_output(self, request: AdapterRequest) -> None:
        """Keep the documented JSON-only stdout as the adapter result."""

        shutil.copyfile(request.stdout_path, request.result_path)

    def evidence(
        self, request: AdapterRequest, session_id: str
    ) -> dict[str, object]:
        return {
            "contract": {
                "entrypoint": "openclaw agent --local",
                "delivery_requested": False,
                "output": "--json reserves stdout for the structured response",
            },
            "fresh_context": {
                "guaranteed_by_adapter": True,
                "mechanism": (
                    "adapter-generated session UUID plus a new private "
                    "OPENCLAW_STATE_DIR"
                ),
                "preexisting_state_rejected": True,
                "session_id": session_id,
                "state_path": str(self._state_path(request)),
                "gap": (
                    "OpenClaw has no ephemeral/no-session-persistence flag; the "
                    "new transcript is retained under the private evidence state"
                ),
            },
            "working_directory": {
                "guaranteed_by_adapter": True,
                "mechanism": (
                    "agents.defaults.workspace in the per-run config and process cwd"
                ),
                "path": str(request.workdir),
            },
            "mcp": {
                "requested": request.mcp_config_path is not None,
                "per_run_injected": request.mcp_config_path is not None,
                "mechanism": (
                    "mcpServers.aoms translated to mcp.servers.aoms in the "
                    "per-run OPENCLAW_CONFIG_PATH"
                    if request.mcp_config_path is not None
                    else "no MCP server requested for this run"
                ),
                "config_path": str(self._config_path(request)),
                "global_config_modified": False,
            },
            "output_capture": {
                "stdout": str(request.stdout_path),
                "stderr": str(request.stderr_path),
                "json_result": str(request.result_path),
            },
        }

    def version(self) -> str:
        return _executable_version("openclaw", "--version")


ADAPTERS: dict[str, AgentAdapter] = {
    adapter.name: adapter
    for adapter in (
        ClaudeAdapter(),
        CodexAdapter(),
        ScriptedAdapter(),
        OpenClawAdapter(),
    )
}


async def launch_fresh_process(
    adapter: AgentAdapter,
    request: AdapterRequest,
    *,
    project_root: Path,
) -> ProcessResult:
    """Launch and fully capture one adapter process without any resume state."""

    session_id = str(uuid4())
    argv = adapter.build_command(request, session_id)
    environment = dict(os.environ)
    existing_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(project_root), existing_path) if item
    )
    environment_builder = getattr(adapter, "environment", None)
    if callable(environment_builder):
        environment.update(environment_builder(request))
    started_at = _utc_now()
    loop = asyncio.get_running_loop()
    started = loop.time()
    with request.stdout_path.open("wb") as stdout, request.stderr_path.open("wb") as stderr:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=request.workdir,
            env=environment,
            stdout=stdout,
            stderr=stderr,
        )
        returncode = await process.wait()
    wall_time = loop.time() - started
    output_capture = getattr(adapter, "capture_output", None)
    if callable(output_capture):
        output_capture(request)
    evidence_builder = getattr(adapter, "evidence", None)
    adapter_evidence = (
        evidence_builder(request, session_id)
        if callable(evidence_builder)
        else {}
    )
    return ProcessResult(
        adapter=adapter.name,
        argv=tuple(argv),
        pid=process.pid,
        returncode=returncode,
        started_at=started_at,
        ended_at=_utc_now(),
        wall_time_seconds=wall_time,
        fresh_session_id=session_id,
        adapter_evidence=adapter_evidence,
    )


__all__ = [
    "ADAPTERS",
    "AdapterRequest",
    "AdapterUnavailable",
    "AgentAdapter",
    "ClaudeAdapter",
    "CodexAdapter",
    "OpenClawAdapter",
    "ProcessResult",
    "ScriptedAdapter",
    "launch_fresh_process",
]
