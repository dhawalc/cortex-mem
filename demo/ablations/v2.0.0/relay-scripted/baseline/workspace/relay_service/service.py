"""In-process relay prototype; durability hardening is the demo task."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping


class RelayStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._seen: set[str] = set()
        self._events: list[dict[str, Any]] = []

    def accept(
        self,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        received_at: str,
    ) -> dict[str, Any]:
        event_id = headers.get("X-Relay-Event")
        if not event_id:
            raise ValueError("X-Relay-Event is required")
        if event_id in self._seen:
            return {"status": "duplicate", "event_id": event_id}
        self._seen.add(event_id)
        self._events.append(
            {
                "event_id": event_id,
                "received_at": received_at,
                "payload": deepcopy(dict(payload)),
            }
        )
        return {"status": "accepted", "event_id": event_id}

    def list_events(self) -> list[dict[str, Any]]:
        return sorted(deepcopy(self._events), key=lambda event: (event["received_at"], event["event_id"]))
