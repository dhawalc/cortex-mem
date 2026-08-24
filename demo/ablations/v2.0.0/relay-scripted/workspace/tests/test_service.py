from pathlib import Path

import pytest

from relay_service import RelayStore


def test_accept_and_list_event(tmp_path: Path) -> None:
    store = RelayStore(tmp_path / "relay.sqlite3")
    result = store.accept(
        {"X-Relay-Event": "event-1"}, {"message": "hello"}, "2026-08-23T10:00:00Z"
    )

    assert result == {"status": "accepted", "event_id": "event-1"}
    assert store.list_events()[0]["payload"] == {"message": "hello"}


def test_duplicate_in_one_instance_is_rejected(tmp_path: Path) -> None:
    store = RelayStore(tmp_path / "relay.sqlite3")
    headers = {"X-Relay-Event": "event-1"}
    store.accept(headers, {"attempt": 1}, "2026-08-23T10:00:00Z")

    duplicate = store.accept(headers, {"attempt": 2}, "2026-08-23T10:00:01Z")

    assert duplicate["status"] == "duplicate"
    assert len(store.list_events()) == 1


def test_event_header_is_required(tmp_path: Path) -> None:
    store = RelayStore(tmp_path / "relay.sqlite3")
    with pytest.raises(ValueError, match="X-Relay-Event"):
        store.accept({}, {}, "2026-08-23T10:00:00Z")
