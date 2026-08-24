from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

import aoms.cli as cli_module
from aoms.activation import (
    ActivationResult,
    InvocationSource,
    detect_invocation_source,
    host_registration_command,
)

ROOT = Path(__file__).resolve().parents[2]
PINNED_SOURCE = InvocationSource(
    (
        "uvx",
        "--from",
        "git+https://github.com/dhawalc/cortex-mem@v2.0.0",
        "cortex-mem",
    ),
    "Git source git+https://github.com/dhawalc/cortex-mem@v2.0.0",
)


def test_git_direct_url_detection_preserves_requested_ref() -> None:
    detected = detect_invocation_source(
        direct_url={
            "url": "https://github.com/dhawalc/cortex-mem",
            "vcs_info": {
                "vcs": "git",
                "requested_revision": "v2.0.0",
                "commit_id": "a" * 40,
            },
        }
    )

    assert detected == PINNED_SOURCE


def test_installed_launcher_detection_preserves_executable(tmp_path: Path) -> None:
    launcher = tmp_path / "bin" / "cortex-mem"
    detected = detect_invocation_source(
        direct_url={}, argv0=str(launcher), executable="/ignored/python"
    )

    assert detected.command == (str(launcher.resolve()),)
    assert detected.description.startswith("installed launcher")


@pytest.mark.parametrize("host", ["claude", "codex", "openclaw"])
def test_setup_registers_exact_source_binds_identity_and_installs_recipe(
    host: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "myproject"
    workspace.mkdir()
    data_dir = tmp_path / "aoms-data"
    registered: list[tuple[str, ...]] = []

    def fake_registration(command: tuple[str, ...]):
        registered.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="host registration ok\n")

    async def fake_activation(*args, **kwargs):
        assert args[0] == PINNED_SOURCE
        assert kwargs["agent_id"] == host
        assert kwargs["workspace"] == workspace.resolve()
        assert kwargs["data_dir"] == data_dir.resolve()
        return ActivationResult("AOMS", "2.0.0", "receipt-fixture", 0, True)

    monkeypatch.setattr(cli_module, "detect_invocation_source", lambda: PINNED_SOURCE)
    monkeypatch.setattr(cli_module, "run_host_registration", fake_registration)
    monkeypatch.setattr(cli_module, "run_activation_check", fake_activation)
    result = CliRunner().invoke(
        cli_module.main,
        [
            "setup",
            host,
            "--workspace",
            str(workspace),
            "--data-dir",
            str(data_dir),
        ],
        env={"AOMS_EMBEDDING_PROVIDER": "none"},
    )

    assert result.exit_code == 0, result.output
    expected = host_registration_command(
        host,
        PINNED_SOURCE,
        agent_id=host,
        workspace=workspace.resolve(),
        data_dir=data_dir.resolve(),
    )
    assert registered == [expected]
    assert f"bound as agent={host} workspace=myproject" in result.output
    assert "handshake=ok recall_sources=0 receipt=receipt-fixture" in result.output
    recipe = data_dir / "recipes" / host
    assert (recipe / "README.md").is_file()
    binding = json.loads((recipe / "aoms-binding.json").read_text())
    assert binding["agent_id"] == host
    assert binding["workspace"] == str(workspace.resolve())
    assert binding["mcp_command"] == [*PINNED_SOURCE.command, "mcp"]
    launcher = Path(binding["bound_launcher"])
    assert launcher.is_file()
    assert "@v2.0.0" in launcher.read_text()
    if host == "claude":
        assert str(launcher) in (recipe / "hooks.json").read_text()
    elif host == "codex":
        assert str(launcher) in (recipe / "config.toml").read_text()
    else:
        assert (
            str(launcher)
            in (recipe / "hooks" / "aoms-recall" / "handler.ts").read_text()
        )


def test_readme_quick_start_is_pinned_and_real() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    command = (
        "uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 "
        "cortex-mem setup claude"
    )

    assert command in readme
    assert "cortex-mem setup <host>" not in readme
