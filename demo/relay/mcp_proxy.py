"""Transparent stdio proxy that records complete MCP JSON-RPC traffic as JSONL.

Only stdout is protocol data. Server stderr is forwarded to proxy stderr, while
each stdin/stdout protocol frame is recorded with a direction and sequence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO


class TrafficWriter:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._sequence = 0
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, direction: str, raw_line: bytes) -> None:
        try:
            message: object = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = {"unparsed_utf8": raw_line.decode("utf-8", errors="replace")}
        with self._lock:
            self._sequence += 1
            event = {
                "sequence": self._sequence,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "direction": direction,
                "message": message,
            }
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False))
                handle.write("\n")


def _forward_protocol(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    direction: str,
    traffic: TrafficWriter,
) -> None:
    try:
        for line in iter(source.readline, b""):
            traffic.write(direction, line)
            destination.write(line)
            destination.flush()
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            destination.close()
        except OSError:
            pass


def _forward_stderr(source: BinaryIO) -> None:
    for chunk in iter(lambda: source.read(8192), b""):
        sys.stderr.buffer.write(chunk)
        sys.stderr.buffer.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traffic", required=True, type=Path)
    parser.add_argument("--server-command-json", required=True)
    parser.add_argument("--server-cwd", type=Path)
    args = parser.parse_args(argv)
    command = json.loads(args.server_command_json)
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        parser.error("--server-command-json must be a JSON array of strings")

    traffic = TrafficWriter(args.traffic)
    args.traffic.touch(exist_ok=True)
    server = subprocess.Popen(
        command,
        cwd=args.server_cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    assert server.stdin is not None
    assert server.stdout is not None
    assert server.stderr is not None
    stdin_thread = threading.Thread(
        target=_forward_protocol,
        args=(sys.stdin.buffer, server.stdin),
        kwargs={"direction": "client_to_server", "traffic": traffic},
        daemon=True,
    )
    stdout_thread = threading.Thread(
        target=_forward_protocol,
        args=(server.stdout, sys.stdout.buffer),
        kwargs={"direction": "server_to_client", "traffic": traffic},
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_forward_stderr,
        args=(server.stderr,),
        daemon=True,
    )
    stdin_thread.start()
    stdout_thread.start()
    stderr_thread.start()
    returncode = server.wait()
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    return returncode


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
