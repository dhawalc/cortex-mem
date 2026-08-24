"""Durable webhook relay implementation produced by scripted replay."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .redaction import redact


class RelayStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        with sqlite3.connect(self.path) as database:
            database.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                "event_id TEXT UNIQUE NOT NULL, "
                "received_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def accept(
        self,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        received_at: str,
    ) -> dict[str, Any]:
        event_id = headers.get("X-Relay-Event")
        if not event_id:
            raise ValueError("X-Relay-Event is required")
        serialized = json.dumps(
            redact(deepcopy(dict(payload))), sort_keys=True
        )
        with sqlite3.connect(self.path) as database:
            cursor = database.execute(
                "INSERT OR IGNORE INTO events(event_id, received_at, payload) "
                "VALUES (?, ?, ?)",
                (event_id, received_at, serialized),
            )
            accepted = cursor.rowcount == 1
        return {
            "status": "accepted" if accepted else "duplicate",
            "event_id": event_id,
        }

    def list_events(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as database:
            rows = database.execute(
                "SELECT event_id, received_at, payload FROM events ORDER BY seq"
            ).fetchall()
        return [
            {
                "event_id": event_id,
                "received_at": received_at,
                "payload": json.loads(payload),
            }
            for event_id, received_at, payload in rows
        ]
