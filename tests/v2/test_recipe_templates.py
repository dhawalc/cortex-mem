from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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
