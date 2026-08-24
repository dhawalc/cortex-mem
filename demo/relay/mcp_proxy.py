"""Budget-enforcing stdio proxy that records MCP JSON-RPC traffic as JSONL.

Only stdout is protocol data. Server stderr is forwarded to proxy stderr, while
each stdin/stdout protocol frame is recorded with a direction and sequence. A
configured recall budget is pinned before calls reach the server; the traffic
record contains the forwarded message plus the client's requested budget.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable

LineTransform = Callable[[bytes], tuple[bytes, dict[str, Any] | None]]


class TrafficWriter:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._sequence = 0
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        direction: str,
        raw_line: bytes,
        *,
        enforcement: dict[str, Any] | None = None,
    ) -> None:
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
            if enforcement is not None:
                event["enforcement"] = enforcement
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False))
                handle.write("\n")


def _forward_protocol(
    source: BinaryIO,
    destination: BinaryIO,
    *,
    direction: str,
    traffic: TrafficWriter,
    transform: LineTransform | None = None,
) -> None:
    try:
        for line in iter(source.readline, b""):
            forwarded, enforcement = (
                transform(line) if transform is not None else (line, None)
            )
            traffic.write(direction, forwarded, enforcement=enforcement)
            destination.write(forwarded)
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


def _pin_recall_token_budget(
    raw_line: bytes, *, token_budget: int
) -> tuple[bytes, dict[str, Any] | None]:
    """Pin recall calls to the scenario budget and retain the requested value."""

    try:
        message = json.loads(raw_line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw_line, None
    if not isinstance(message, dict) or message.get("method") != "tools/call":
        return raw_line, None
    parameters = message.get("params")
    if not isinstance(parameters, dict) or parameters.get("name") != "recall":
        return raw_line, None
    arguments = parameters.get("arguments")
    if not isinstance(arguments, dict):
        return raw_line, None

    requested = arguments.get("token_budget")
    arguments["token_budget"] = token_budget
    forwarded = (
        json.dumps(message, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    )
    return forwarded, {
        "recall_token_budget": {
            "requested": requested,
            "pinned": token_budget,
        }
    }


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traffic", required=True, type=Path)
    parser.add_argument("--server-command-json", required=True)
    parser.add_argument("--server-cwd", type=Path)
    parser.add_argument("--recall-token-budget", type=_positive_int)
    args = parser.parse_args(argv)
    command = json.loads(args.server_command_json)
    if not isinstance(command, list) or not all(
        isinstance(item, str) for item in command
    ):
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
        kwargs={
            "direction": "client_to_server",
            "traffic": traffic,
            "transform": (
                None
                if args.recall_token_budget is None
                else lambda line: _pin_recall_token_budget(
                    line, token_budget=args.recall_token_budget
                )
            ),
        },
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
