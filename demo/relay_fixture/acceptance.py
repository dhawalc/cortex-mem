"""Deterministic black-box acceptance checks for a completed relay workspace."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from types import ModuleType


def _load_service(workspace: Path) -> ModuleType:
    service_path = workspace / "relay_service" / "service.py"
    if not service_path.is_file():
        raise AssertionError(f"completed service is missing: {service_path}")
    spec = importlib.util.spec_from_file_location("relay_completed_service", service_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import completed service: {service_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_acceptance(workspace: Path) -> list[str]:
    """Return passed check names, raising AssertionError on the first failure."""

    module = _load_service(workspace)
    relay_store = getattr(module, "RelayStore", None)
    if relay_store is None:
        raise AssertionError("relay_service.service must expose RelayStore")
    passed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="aoms-relay-acceptance-") as directory:
        db_path = Path(directory) / "relay.sqlite3"
        headers = {"X-Relay-Event": "evt-z"}
        timestamp = "2026-08-23T10:15:00.000Z"

        first = relay_store(db_path)
        accepted = first.accept(headers, {"value": "first"}, timestamp)
        assert accepted["status"] == "accepted"
        restarted = relay_store(db_path)
        duplicate = restarted.accept(headers, {"value": "replacement"}, timestamp)
        assert duplicate["status"] == "duplicate"
        assert restarted.list_events()[0]["payload"]["value"] == "first"
        passed.append("durable idempotency")

        restarted.accept(
            {"X-Relay-Event": "evt-b"}, {"value": "second"}, timestamp
        )
        restarted.accept(
            {"X-Relay-Event": "evt-a"}, {"value": "third"}, timestamp
        )
        ids = [event["event_id"] for event in restarted.list_events()]
        assert ids == ["evt-z", "evt-b", "evt-a"], ids
        passed.append("stable equal-timestamp order")

        secret_one = "secret-never-on-disk-7319"  # gitleaks:allow - test sentinel
        secret_two = "nested-secret-never-on-disk-7319"
        restarted.accept(
            {"X-Relay-Event": "evt-secret"},
            {
                "access_token": secret_one,
                "nested": [{"refresh_token": secret_two}, {"safe": "visible"}],
            },
            "2026-08-23T10:16:00.000Z",
        )
        disk_bytes = db_path.read_bytes()
        assert secret_one.encode() not in disk_bytes
        assert secret_two.encode() not in disk_bytes
        redacted = restarted.list_events()[-1]["payload"]
        assert redacted["access_token"] == "[REDACTED]"
        assert redacted["nested"][0]["refresh_token"] == "[REDACTED]"
        passed.append("recursive token redaction before persistence")

    return passed


__all__ = ["run_acceptance"]
