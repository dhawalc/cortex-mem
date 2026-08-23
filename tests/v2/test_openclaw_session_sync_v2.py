from __future__ import annotations

import json
import shutil
from pathlib import Path

from recipes.openclaw.session_sync_v2 import CapturedMemory, SyncConfig, sync_sessions

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "v2" / "fixtures" / "openclaw" / "session-alpha.jsonl"


class IdempotentSink:
    def __init__(self) -> None:
        self.records: dict[str, CapturedMemory] = {}
        self.attempts: list[str] = []

    def __call__(self, memory: CapturedMemory, _: SyncConfig) -> None:
        self.attempts.append(memory.idempotency_key)
        self.records[memory.idempotency_key] = memory


def test_session_sync_is_selective_incremental_and_idempotent(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    shutil.copyfile(FIXTURE, sessions_dir / "session-alpha.jsonl")
    state_file = tmp_path / "state" / "sync.json"
    config = SyncConfig(
        sessions_dir=sessions_dir,
        state_file=state_file,
        agent_id="openclaw-test",
        workspace="fixture-workspace",
    )
    sink = IdempotentSink()

    first_count = sync_sessions(config, rememberer=sink)
    first_keys = list(sink.attempts)
    second_count = sync_sessions(config, rememberer=sink)

    assert first_count == 3
    assert second_count == 0
    assert len(sink.records) == 3
    assert all(key.startswith("openclaw-session-v2:session-alpha:") for key in first_keys)
    contents = "\n".join(item.content for item in sink.records.values())
    assert "SQLite WAL" in contents
    assert "process environment" in contents
    assert "stable key" in contents
    assert "Background chatter" not in contents
    assert "hidden reasoning" not in contents
    assert "fixture-secret-value" not in contents

    # Simulate cursor-state loss. Stable session+byte-position keys replay as
    # updates at the sink rather than creating any additional logical records.
    state = json.loads(state_file.read_text(encoding="utf-8"))
    for file_state in state["files"].values():
        file_state["offset"] = 0
    state_file.write_text(json.dumps(state), encoding="utf-8")
    replay_count = sync_sessions(config, rememberer=sink)

    assert replay_count == 3
    assert sink.attempts[3:] == first_keys
    assert len(sink.records) == 3
