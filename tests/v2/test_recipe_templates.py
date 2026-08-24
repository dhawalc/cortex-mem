from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINNED_SETUP = (
    "uvx --from git+https://github.com/dhawalc/cortex-mem@v2.0.0 "
    "cortex-mem setup"
)


def test_claude_code_hook_template_is_valid_json_with_session_contract() -> None:
    template = json.loads(
        (ROOT / "recipes" / "claude-code" / "hooks.json").read_text(
            encoding="utf-8"
        )
    )

    session_start = template["hooks"]["SessionStart"]
    assert len(session_start) == 1
    handler = session_start[0]["hooks"][0]
    assert handler["type"] == "command"
    assert "cortex-mem recall" in handler["command"]
    assert "--budget 2000" in handler["command"]
    assert 'hookEventName:\"SessionStart\"' in handler["command"]
    assert "additionalContext" in handler["command"]


def test_packaged_recipe_docs_lead_with_pinned_setup() -> None:
    expected_hosts = {
        "recipes/README.md": ("claude", "codex", "openclaw"),
        "recipes/claude-code/README.md": ("claude",),
        "recipes/codex/README.md": ("codex",),
        "recipes/openclaw/README.md": ("openclaw",),
    }

    for relative_path, hosts in expected_hosts.items():
        document = (ROOT / relative_path).read_text(encoding="utf-8")
        for host in hosts:
            assert f"{PINNED_SETUP} {host}" in document


def test_packaged_recipe_docs_do_not_restore_unbound_registration_paths() -> None:
    documents = "\n".join(
        (ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in (
            "recipes/README.md",
            "recipes/claude-code/README.md",
            "recipes/codex/README.md",
            "recipes/openclaw/README.md",
        )
    )

    assert "claude mcp add --scope user" not in documents
    assert 'args = ["cortex-mem", "mcp"]' not in documents
    assert "Do not replace" in documents


def test_relay_docs_include_source_install_prerequisites() -> None:
    for relative_path in ("README.md", "demo/relay/README.md"):
        document = (ROOT / relative_path).read_text(encoding="utf-8")
        relay_command = document.index("python -m demo.relay.runner run")
        prerequisites = document[max(0, relay_command - 500) : relay_command]
        assert "git clone --branch v2.0.0 --depth 1" in prerequisites
        assert 'python -m pip install -e ".[dev]"' in prerequisites
