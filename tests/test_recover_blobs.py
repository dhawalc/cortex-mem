import json
from pathlib import Path

import pytest

from scripts.recover_blobs_v2 import recover, validate_paths, verify_outputs


SCHEMA = b'{  "schema" : "test.record.v1", "fields": ["id", "ts"]  }'


def _write_blob(root: Path, relative: str, parts: list[bytes]) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(parts))
    return path


def _record(entry_id: str, **values: object) -> bytes:
    return json.dumps({"id": entry_id, **values}, separators=(",", ":")).encode()


def test_id_dedup_keeps_newest_selected_timestamp_and_first_ties(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    _write_blob(
        source,
        "semantic/facts.jsonl",
        [
            SCHEMA,
            _record("by-decay", ts="2026-08-03T00:00:00Z", value="old"),
            _record(
                "by-decay",
                ts="2026-01-01T00:00:00Z",
                _decay_applied_at="2026-08-04T00:00:00Z",
                value="new",
            ),
            _record("fallback", ts="2026-08-05T00:00:00Z", value="first"),
            _record("fallback", ts="2026-08-05T00:00:00Z", value="later-tie"),
            _record(
                "field-order",
                _decay_applied_at="2026-01-01T00:00:00Z",
                ts="2030-01-01T00:00:00Z",
                value="decay-is-selected",
            ),
            _record("field-order", ts="2026-02-01T00:00:00Z", value="newer-selected-ts"),
        ],
    )

    report = recover(source, output, verify=True)

    lines = [json.loads(line) for line in (output / "semantic/facts.jsonl").read_bytes().splitlines()]
    records = {item["id"]: item for item in lines if "id" in item}
    assert records["by-decay"]["value"] == "new"
    assert records["fallback"]["value"] == "first"
    assert records["field-order"]["value"] == "newer-selected-ts"
    assert report["summary"]["objects"] == 6
    assert report["summary"]["unique_ids"] == 3
    assert report["summary"]["duplicates_dropped"] == 3
    assert report["verification"]["ok"] is True


def test_content_dedup_uses_stable_content_and_preserves_schema(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    _write_blob(
        source,
        "semantic/facts.jsonl",
        [
            SCHEMA,
            _record(
                "old-content-id",
                ts="2026-08-01T00:00:00Z",
                kind="same-content",
                value="same",
            ),
            _record(
                "new-content-id",
                ts="2026-08-02T00:00:00Z",
                kind="same-content",
                value="same",
            ),
            _record("reused-id", kind="distinct-a", value="alpha"),
            _record("reused-id", kind="distinct-b", value="beta"),
            _record(
                "volatile-old",
                kind="volatile-only",
                value="stable",
                ts="2026-08-03T00:00:00Z",
                _written_at="2026-08-03T01:00:00Z",
                _decay_applied_at="2026-08-03T02:00:00Z",
                weight=0.1,
                _indexed_at="old",
                line_number=10,
                _migrated_at="old",
                _source_line=100,
            ),
            _record(
                "volatile-new",
                kind="volatile-only",
                value="stable",
                ts="2026-08-04T00:00:00Z",
                _written_at="2026-08-04T01:00:00Z",
                _decay_applied_at="2026-08-04T02:00:00Z",
                weight=0.9,
                _indexed_at="new",
                line_number=20,
                _migrated_at="new",
                _source_line=200,
            ),
        ],
    )

    report = recover(source, output, verify=True, dedup_mode="content")

    output_file = output / "semantic/facts.jsonl"
    raw_lines = output_file.read_bytes().splitlines()
    records = [json.loads(line) for line in raw_lines[1:]]
    assert raw_lines[0] == SCHEMA
    assert {item["id"] for item in records if item["kind"] == "same-content"} == {
        "new-content-id"
    }
    assert [item["value"] for item in records if item["id"] == "reused-id"] == [
        "alpha",
        "beta",
    ]
    assert {item["id"] for item in records if item["kind"] == "volatile-only"} == {
        "volatile-new"
    }
    file_report = report["files"][0]
    assert file_report["objects"] == 6
    assert file_report["unique_contents"] == 4
    assert file_report["content_duplicates_dropped"] == 2
    assert file_report["dup_ratio"] == pytest.approx(2 / 6)
    assert file_report["projected_output_bytes"] == output_file.stat().st_size
    assert report["summary"]["unique_contents"] == 4
    assert report["summary"]["content_duplicates_dropped"] == 2
    assert report["verification"]["ok"] is True


def test_content_dedup_exact_ties_keep_first_seen(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    _write_blob(
        source,
        "procedural/skills.jsonl",
        [
            _record("first", ts="2026-08-01T00:00:00Z", value="same"),
            _record("second", ts="2026-08-01T00:00:00Z", value="same"),
        ],
    )

    recover(source, output, dedup_mode="content", verify=True)

    record = json.loads((output / "procedural/skills.jsonl").read_text())
    assert record["id"] == "first"


def test_schema_object_bytes_are_preserved_when_embedded_in_blob(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    _write_blob(
        source,
        "episodic/decisions.jsonl",
        [SCHEMA, _record("one", ts="2026-08-01T00:00:00Z")],
    )

    recover(source, output, verify=True)

    first_line = (output / "episodic/decisions.jsonl").read_bytes().splitlines()[0]
    assert first_line == SCHEMA


def test_unparseable_byte_spans_are_reported_and_scanning_continues(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    valid = _record("healthy", ts="2026-08-01T00:00:00Z")
    payload = b"junk!" + valid + b'{"bad": nope}' + b'{"trailing":'
    _write_blob(source, "procedural/patterns.jsonl", [payload])

    report = recover(source, output, verify=True)

    file_report = report["files"][0]
    assert [item["reason"] for item in file_report["unparseable_spans"]] == [
        "non_json_bytes",
        "invalid_json_object",
        "truncated_object_at_eof",
    ]
    assert file_report["objects"] == 1
    assert file_report["winners_selected"] == 1
    assert json.loads((output / "procedural/patterns.jsonl").read_text())["id"] == "healthy"


def test_verify_reports_invalid_json_and_duplicate_id(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    _write_blob(source, "semantic/facts.jsonl", [_record("one", ts="2026-08-01T00:00:00Z")])
    report = recover(source, output, verify=True)
    output_file = output / "semantic/facts.jsonl"
    with output_file.open("ab") as handle:
        handle.write(_record("one", ts="2026-08-02T00:00:00Z") + b"\n")
        handle.write(b"not json\n")

    verification = verify_outputs(output, report["files"])

    assert verification["ok"] is False
    messages = [failure["error"] for failure in verification["failures"]]
    assert any("duplicate id in tier" in message for message in messages)
    assert any("invalid JSON" in message for message in messages)
    assert any("data line count" in message for message in messages)


def test_path_safety_rejects_output_inside_input_and_live_read_without_flag(tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.mkdir()
    with pytest.raises(ValueError, match="inside the input"):
        validate_paths(source, source / "recovered", allow_live_read=False)

    from scripts.recover_blobs_v2 import LIVE_MEMORY_DIR

    with pytest.raises(ValueError, match="allow-live-read"):
        validate_paths(LIVE_MEMORY_DIR, tmp_path / "elsewhere", allow_live_read=False)

    with pytest.raises(ValueError, match="never be inside live memory"):
        validate_paths(source, LIVE_MEMORY_DIR / "unsafe-output", allow_live_read=False)
