#!/usr/bin/env python3
"""Selectively sync durable OpenClaw transcript markers through the AOMS CLI.

This is intentionally not transcript ingestion. Only explicit, one-line
Decision/Failure/Learning markers are eligible, and likely secrets are rejected.
Byte cursors make normal runs incremental; stable session+position keys make a
replayed line an idempotent update rather than a duplicate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_SESSIONS_DIR = Path("~/.openclaw/agents/main/sessions").expanduser()
DEFAULT_STATE_FILE = Path(
    "~/.local/state/aoms/openclaw-session-sync-v2.json"
).expanduser()
MAX_CAPTURE_CHARS = 1_200
MIN_CAPTURE_CHARS = 12

MARKER_RE = re.compile(
    r"^\s*(?:[-*]\s+|#{1,6}\s+)?(?:\*\*)?\[?"
    r"(?P<label>decision|decided|failure|failed|learning|learned|lesson)"
    r"\]?(?:\*\*)?\s*(?::|[-—])\s*(?:\*\*)?(?P<body>\S.*)$",
    re.IGNORECASE,
)
SENSITIVE_RES = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(
        r"\b(?:api[_ -]?key|access[_ -]?token|password|secret|credential)"
        r"\s*[:=]\s*[^\s,;]{6,}",
        re.IGNORECASE,
    ),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


@dataclass(frozen=True, slots=True)
class SyncConfig:
    sessions_dir: Path
    state_file: Path
    cortex_mem: str = "cortex-mem"
    agent_id: str = "openclaw"
    workspace: str = "default"


@dataclass(frozen=True, slots=True)
class CapturedMemory:
    content: str
    kind: str
    tags: tuple[str, ...]
    idempotency_key: str
    session_id: str
    byte_offset: int
    marker_index: int


Rememberer = Callable[[CapturedMemory, SyncConfig], None]


class FileLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            import fcntl

            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.fd)
            self.fd = None
            raise RuntimeError("session sync is already running") from exc
        return self

    def __exit__(self, *_: object) -> None:
        if self.fd is None:
            return
        try:
            import fcntl

            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 2, "files": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 2, "files": {}}
    if not isinstance(value, dict) or not isinstance(value.get("files"), dict):
        return {"version": 2, "files": {}}
    return value


def save_state(state: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def normalize_content(content: Any) -> str:
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
    else:
        parts = []
    return "\n".join(part for part in parts if part).strip()


def looks_sensitive(text: str) -> bool:
    return any(pattern.search(text) for pattern in SENSITIVE_RES)


def extract_memories(
    raw_line: str, *, session_id: str, byte_offset: int
) -> list[CapturedMemory]:
    try:
        entry = json.loads(raw_line)
    except json.JSONDecodeError:
        return []
    if entry.get("type") != "message":
        return []
    message = entry.get("message")
    if not isinstance(message, dict) or message.get("role") not in {
        "user",
        "assistant",
    }:
        return []
    role = str(message["role"])
    text = normalize_content(message.get("content"))
    captured: list[CapturedMemory] = []
    for line in text.splitlines():
        match = MARKER_RE.match(line)
        if match is None:
            continue
        label = match.group("label").casefold()
        category = (
            "decision"
            if label in {"decision", "decided"}
            else "failure"
            if label in {"failure", "failed"}
            else "learning"
        )
        body = " ".join(match.group("body").split())
        content = f"{category.capitalize()}: {body}"[:MAX_CAPTURE_CHARS].rstrip()
        if len(content) < MIN_CAPTURE_CHARS or looks_sensitive(content):
            continue
        marker_index = len(captured)
        captured.append(
            CapturedMemory(
                content=content,
                kind={
                    "decision": "decision",
                    "failure": "failure",
                    "learning": "fact",
                }[category],
                tags=(
                    "openclaw",
                    "session-sync-v2",
                    category,
                    role,
                    f"session:{session_id}",
                ),
                idempotency_key=(
                    f"openclaw-session-v2:{session_id}:{byte_offset}:{marker_index}"
                ),
                session_id=session_id,
                byte_offset=byte_offset,
                marker_index=marker_index,
            )
        )
    return captured


def remember_via_cli(memory: CapturedMemory, config: SyncConfig) -> None:
    environment = dict(os.environ)
    environment["AOMS_AGENT_ID"] = config.agent_id
    environment["AOMS_WORKSPACE"] = config.workspace
    command = [
        config.cortex_mem,
        "remember",
        "--content",
        memory.content,
        "--kind",
        memory.kind,
        "--tags",
        ",".join(memory.tags),
        "--idempotency-key",
        memory.idempotency_key,
    ]
    completed = subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"cortex-mem remember failed for {memory.idempotency_key}: {detail}"
        )


def _session_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.glob("*.jsonl")
        if ".trajectory." not in path.name
    )


def sync_sessions(
    config: SyncConfig, *, rememberer: Rememberer = remember_via_cli
) -> int:
    state = load_state(config.state_file)
    state_files = state.setdefault("files", {})
    captured_count = 0
    config.sessions_dir.mkdir(parents=True, exist_ok=True)

    for path in _session_files(config.sessions_dir):
        file_key = str(path.resolve())
        file_state = state_files.get(file_key, {})
        offset = int(file_state.get("offset", 0))
        size = path.stat().st_size
        if offset < 0 or size < offset:
            offset = 0
        session_id = path.stem
        with path.open("rb") as handle:
            handle.seek(offset)
            while True:
                line_offset = handle.tell()
                raw_line = handle.readline()
                if not raw_line:
                    break
                next_offset = handle.tell()
                memories = extract_memories(
                    raw_line.decode("utf-8", errors="replace"),
                    session_id=session_id,
                    byte_offset=line_offset,
                )
                for memory in memories:
                    rememberer(memory, config)
                    captured_count += 1
                # Advance only after every eligible memory on the line succeeded.
                offset = next_offset
        state_files[file_key] = {
            "offset": offset,
            "session_id": session_id,
            "size": size,
        }
        save_state(state, config.state_file)
    return captured_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-dir", type=Path, default=DEFAULT_SESSIONS_DIR)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--cortex-mem", default="cortex-mem")
    parser.add_argument("--agent-id", default="openclaw")
    parser.add_argument(
        "--workspace",
        default=os.environ.get("AOMS_WORKSPACE", "default"),
        help="AOMS workspace identity (default: AOMS_WORKSPACE or 'default').",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = SyncConfig(
        sessions_dir=args.sessions_dir.expanduser(),
        state_file=args.state_file.expanduser(),
        cortex_mem=args.cortex_mem,
        agent_id=args.agent_id,
        workspace=args.workspace,
    )
    lock_file = config.state_file.with_suffix(config.state_file.suffix + ".lock")
    try:
        with FileLock(lock_file):
            count = sync_sessions(config)
    except (OSError, RuntimeError) as exc:
        print(f"session-sync-v2: {exc}", file=sys.stderr)
        return 1
    print(f"Captured {count} durable OpenClaw marker(s) in AOMS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
