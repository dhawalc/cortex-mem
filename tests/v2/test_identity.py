"""Agent identity must be one value per host, derived from one place.

These tests exist because the divergence they catch is silent. Nothing raises
when the packaged Claude hook recalls as ``claude-code`` and the MCP server
that ``setup claude`` registered writes as ``claude`` — agent-private scope
just splits in half and the isolation claim quietly stops holding.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from aoms import cli as cli_module
from aoms.activation import HOST_RECIPE_DIRECTORIES
from aoms.adapters import mcp_server
from aoms.identity import (
    DEFAULT_AGENT_ID,
    OPENCLAW_SUBAGENT_PREFIX,
    SUPPORTED_HOSTS,
    agent_id_for_host,
    resolved_agent_id,
)

RECIPES_ROOT = Path(__file__).resolve().parents[2] / "recipes"

# A *literal* binding of the environment variable, in the formats the recipes
# use: a shell command prefix, or a quoted JSON/TOML/TypeScript member. A
# binding to a variable (``AOMS_AGENT_ID: agentId``) matches neither, on
# purpose — those are checked one by one below, at their definitions.
LITERAL_AGENT_ID_BINDINGS = (
    re.compile(r"""AOMS_AGENT_ID=([A-Za-z0-9_.-]+)"""),
    re.compile(r"""AOMS_AGENT_ID["']?\s*[:=]\s*["']([^"']+)["']"""),
)


def _literal_bindings(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:  # pragma: no cover - binary recipe asset
        return []
    return [value for pattern in LITERAL_AGENT_ID_BINDINGS for value in pattern.findall(text)]


def _recipe_files(host: str) -> list[Path]:
    directory = RECIPES_ROOT / HOST_RECIPE_DIRECTORIES[host]
    return [
        path
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]


def test_supported_hosts_and_recipe_directories_agree() -> None:
    assert tuple(HOST_RECIPE_DIRECTORIES) == SUPPORTED_HOSTS


def test_setup_command_offers_exactly_the_supported_hosts() -> None:
    host_argument = next(
        parameter
        for parameter in cli_module.setup_command.params
        if parameter.name == "host"
    )
    assert tuple(host_argument.type.choices) == SUPPORTED_HOSTS


def test_setup_binds_the_canonical_identity_for_every_host() -> None:
    for host in SUPPORTED_HOSTS:
        assert agent_id_for_host(host) == host
        assert agent_id_for_host(host.upper()) == host


def test_agent_id_for_host_rejects_unknown_hosts() -> None:
    with pytest.raises(ValueError, match="unsupported host"):
        agent_id_for_host("cursor")


@pytest.mark.parametrize("host", SUPPORTED_HOSTS)
def test_packaged_recipes_bind_the_canonical_identity(host: str) -> None:
    """Every AOMS_AGENT_ID literal shipped in a recipe matches its host."""

    canonical = agent_id_for_host(host)
    for path in _recipe_files(host):
        for value in _literal_bindings(path):
            assert value == canonical, (
                f"{path} binds AOMS_AGENT_ID={value!r}, but the canonical "
                f"identity for host {host!r} is {canonical!r}"
            )


def test_claude_and_codex_recipes_bind_their_identity_literally() -> None:
    """The two hosts whose recipes are copy-pasted must state the identity."""

    for host in ("claude", "codex"):
        bindings = [
            value for path in _recipe_files(host) for value in _literal_bindings(path)
        ]
        assert bindings, f"no AOMS_AGENT_ID binding found in the {host} recipe"


def test_openclaw_binds_identities_derived_from_the_host_name() -> None:
    """OpenClaw binds indirectly, so check both bindings at their definitions.

    The recall hook refines the identity per sub-agent
    (``openclaw-<subagent>``); the session sync binds the bare host identity.
    Both must stay derived from ``agent_id_for_host("openclaw")``.
    """

    canonical = agent_id_for_host("openclaw")
    assert OPENCLAW_SUBAGENT_PREFIX == f"{canonical}-"

    handler = (
        RECIPES_ROOT / "openclaw" / "hooks" / "aoms-recall" / "handler.ts"
    ).read_text(encoding="utf-8")
    assert "AOMS_AGENT_ID: agentId" in handler
    assert f"`{OPENCLAW_SUBAGENT_PREFIX}${{" in handler

    sync = (RECIPES_ROOT / "openclaw" / "session_sync_v2.py").read_text(
        encoding="utf-8"
    )
    assert 'environment["AOMS_AGENT_ID"] = config.agent_id' in sync
    assert f'agent_id: str = "{canonical}"' in sync


def test_every_transport_shares_one_unbound_fallback() -> None:
    """An unbound CLI and an unbound MCP server must not disagree."""

    for unset in (None, "", "   "):
        assert resolved_agent_id(unset) == DEFAULT_AGENT_ID
    assert resolved_agent_id("  bound-agent ") == "bound-agent"


def test_cli_and_mcp_resolve_an_unset_identity_identically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("AOMS_AGENT_ID", raising=False)
    monkeypatch.setenv("AOMS_WORKSPACE", str(tmp_path))

    cli_context = cli_module._scope_context()
    mcp_context = mcp_server._scope_context_from_environ(
        {"AOMS_WORKSPACE": str(tmp_path)}
    )

    assert cli_context.agent_id == mcp_context.agent_id == DEFAULT_AGENT_ID

    monkeypatch.setenv("AOMS_AGENT_ID", "bound-agent")
    assert cli_module._scope_context().agent_id == "bound-agent"
    assert (
        mcp_server._scope_context_from_environ(
            {"AOMS_AGENT_ID": "bound-agent", "AOMS_WORKSPACE": str(tmp_path)}
        ).agent_id
        == "bound-agent"
    )


@pytest.mark.parametrize("host", SUPPORTED_HOSTS)
def test_packaged_recipes_contain_no_placeholder_paths(host: str) -> None:
    """A copy-paste user must never be handed a path they have to notice."""

    for path in _recipe_files(host):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - binary recipe asset
            continue
        for placeholder in ("/absolute/path/to", "/path/to/your", "<your-"):
            assert placeholder not in text, (
                f"{path} ships the placeholder {placeholder!r}; a user who "
                "copies this file gets a broken configuration"
            )


def test_codex_recipe_is_valid_toml_and_omits_a_guessed_workspace() -> None:
    config = tomllib.loads(
        (RECIPES_ROOT / "codex" / "config.toml").read_text(encoding="utf-8")
    )
    environment = config["mcp_servers"]["aoms"]["env"]
    assert environment["AOMS_AGENT_ID"] == agent_id_for_host("codex")
    assert "AOMS_WORKSPACE" not in environment


def test_claude_recipe_is_valid_json_and_binds_the_canonical_identity() -> None:
    hooks = json.loads(
        (RECIPES_ROOT / "claude-code" / "hooks.json").read_text(encoding="utf-8")
    )
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert f"AOMS_AGENT_ID={agent_id_for_host('claude')} " in command
