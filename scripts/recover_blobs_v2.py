#!/usr/bin/env python3
"""Safely recover concatenated AOMS JSON objects into clean JSONL files.

The input tree is always opened read-only.  Recovery is tier-wide: records with
the same deduplication key anywhere in one tier are deduplicated, while the
winning record is emitted into the mirrored file corresponding to its original
input file.  The default key is ``id``; content mode hashes the record after
removing known volatile metadata fields.

For each record, the selection timestamp is the first *parseable* value found
in this order: ``_decay_applied_at``, ``ts``, then ``_written_at``.  Duplicate
keys keep the record with the newest selected timestamp.  Timestamp-field
priority breaks equal-timestamp ties.  Complete ties keep the first input
occurrence deterministically, including records without a parseable timestamp.

The scanner tracks JSON braces and strings across fixed-size byte chunks.  It
never reads a physical line or a whole file into memory; only one JSON object
is materialized at a time.  Unparseable byte ranges are recorded in the report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence


CHUNK_SIZE = 1024 * 1024
REPORT_NAME = "recovery_report.json"
TIMESTAMP_FIELDS = ("_decay_applied_at", "ts", "_written_at")
VOLATILE = {
    "id",
    "ts",
    "_written_at",
    "_decay_applied_at",
    "weight",
    "_indexed_at",
    "line_number",
    "_migrated_at",
    "_source_line",
}
DEDUP_MODES = ("id", "content")
LIVE_MEMORY_DIR = (Path(__file__).resolve().parents[1] / "modules" / "memory").resolve()

# timestamp, timestamp-field priority, input sequence, source file index,
# newline-terminated output bytes
Winner = tuple[float, int, int, int, int]


@dataclass(slots=True)
class JsonObject:
    value: Any
    raw: bytes
    start: int
    end: int


def _span(start: int, end: int, reason: str) -> dict[str, Any]:
    return {
        "start_byte": start,
        "end_byte": end,
        "length_bytes": end - start,
        "reason": reason,
    }


def iter_json_objects(
    path: Path,
    on_unparseable: Callable[[dict[str, Any]], None] | None = None,
    chunk_size: int = CHUNK_SIZE,
) -> Iterator[JsonObject]:
    """Yield balanced top-level JSON objects without loading whole lines.

    JSONL does not permit a literal newline inside an unfinished JSON value.
    An unclosed candidate is therefore reported and reset at newline, which
    lets scanning resume at the next healthy physical line.  The same recovery
    rule is used by the service's streaming statistics scanner.
    """

    report_bad = on_unparseable or (lambda _item: None)
    parts: list[bytes] = []
    depth = 0
    in_string = False
    escaped = False
    candidate_start: int | None = None
    segment_start: int | None = None
    junk_start: int | None = None
    absolute = 0

    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            for index, byte in enumerate(chunk):
                position = absolute + index

                if depth == 0:
                    if byte == 0x7B:  # {
                        if junk_start is not None:
                            report_bad(_span(junk_start, position, "non_json_bytes"))
                            junk_start = None
                        depth = 1
                        in_string = False
                        escaped = False
                        candidate_start = position
                        segment_start = index
                    elif byte not in b" \t\r\n":
                        if junk_start is None:
                            junk_start = position
                    continue

                if in_string:
                    if escaped:
                        escaped = False
                    elif byte == 0x5C:  # backslash
                        escaped = True
                    elif byte == 0x22:  # quote
                        in_string = False
                    # Literal newlines are invalid even inside JSON strings.
                    elif byte == 0x0A:
                        assert candidate_start is not None
                        report_bad(_span(candidate_start, position + 1, "unclosed_object_at_newline"))
                        parts.clear()
                        depth = 0
                        in_string = False
                        escaped = False
                        candidate_start = None
                        segment_start = None
                    continue

                if byte == 0x22:
                    in_string = True
                elif byte == 0x7B:
                    depth += 1
                elif byte == 0x7D:
                    depth -= 1
                    if depth == 0:
                        assert candidate_start is not None and segment_start is not None
                        raw = b"".join(parts) + chunk[segment_start : index + 1]
                        try:
                            value = json.loads(raw)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            report_bad(_span(candidate_start, position + 1, "invalid_json_object"))
                        else:
                            yield JsonObject(value=value, raw=raw, start=candidate_start, end=position + 1)
                        parts.clear()
                        candidate_start = None
                        segment_start = None
                elif byte == 0x0A:
                    assert candidate_start is not None
                    report_bad(_span(candidate_start, position + 1, "unclosed_object_at_newline"))
                    parts.clear()
                    depth = 0
                    candidate_start = None
                    segment_start = None

            if depth and segment_start is not None:
                parts.append(chunk[segment_start:])
                segment_start = 0
            absolute += len(chunk)

    if depth and candidate_start is not None:
        report_bad(_span(candidate_start, absolute, "truncated_object_at_eof"))
    if junk_start is not None:
        report_bad(_span(junk_start, absolute, "non_json_bytes"))


def is_schema(value: Any) -> bool:
    return isinstance(value, dict) and "schema" in value and "id" not in value


def canonical_id(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_key(record: dict[str, Any]) -> str:
    """Return the requested SHA-1 key for a record's stable content."""

    stable = {key: value for key, value in record.items() if key not in VOLATILE}
    serialized = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(serialized.encode("utf-8"), usedforsecurity=False).hexdigest()


def _parse_timestamp(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None and math.isfinite(numeric):
        return numeric
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def selection_key(record: dict[str, Any], sequence: int) -> tuple[float, int, int]:
    """Return (selected timestamp, field priority, input sequence)."""

    for index, field in enumerate(TIMESTAMP_FIELDS):
        parsed = _parse_timestamp(record.get(field))
        if parsed is not None:
            # Earlier TIMESTAMP_FIELDS entries have higher tie-break priority.
            # Sequence identifies the winner but is deliberately not compared:
            # exact timestamp/priority ties keep the first-seen record.
            return parsed, len(TIMESTAMP_FIELDS) - index, sequence
    return -math.inf, 0, sequence


def tier_for(relative_path: Path) -> str:
    return relative_path.parts[0] if len(relative_path.parts) > 1 else "."


def discover_files(input_dir: Path) -> list[Path]:
    return sorted(path for path in input_dir.rglob("*.jsonl") if path.is_file())


def validate_paths(input_dir: Path, output_dir: Path, allow_live_read: bool) -> tuple[Path, Path]:
    input_dir = input_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not input_dir.is_dir():
        raise ValueError(f"input directory does not exist or is not a directory: {input_dir}")
    if output_dir == input_dir or output_dir.is_relative_to(input_dir):
        raise ValueError("output directory must not equal or be inside the input directory")
    if output_dir == LIVE_MEMORY_DIR or output_dir.is_relative_to(LIVE_MEMORY_DIR):
        raise ValueError(f"output directory must never be inside live memory: {LIVE_MEMORY_DIR}")
    if input_dir == LIVE_MEMORY_DIR and not allow_live_read:
        raise ValueError(
            f"refusing to read live memory directory without --allow-live-read: {LIVE_MEMORY_DIR}"
        )
    return input_dir, output_dir


def _empty_file_report(relative: Path, path: Path) -> dict[str, Any]:
    return {
        "path": relative.as_posix(),
        "tier": tier_for(relative),
        "input_bytes": path.stat().st_size,
        "input_bytes_after_scan": None,
        "input_changed_during_scan": False,
        "objects": 0,
        "id_objects": 0,
        "unique_ids": 0,
        "unique_contents": None,
        "schema_lines": 0,
        "missing_id_objects": 0,
        "duplicates_dropped": 0,
        "content_duplicates_dropped": None,
        "dup_ratio": 0.0,
        "winners_selected": 0,
        "projected_output_bytes": 0,
        "output_lines": 0,
        "output_bytes": 0,
        "unparseable_spans": [],
    }


def _scan_tier(
    input_dir: Path,
    files: Sequence[Path],
    reports: dict[str, dict[str, Any]],
    dedup_mode: str,
) -> dict[str, Winner]:
    """Pass 1: select one winner per tier-wide ID or stable-content key."""

    winners: dict[str, Winner] = {}
    sequence = 0
    for file_index, path in enumerate(files):
        relative = path.relative_to(input_dir)
        report = reports[relative.as_posix()]
        seen_ids_in_file: set[str] = set()
        seen_contents_in_file: set[str] | None = set() if dedup_mode == "content" else None
        spans: list[dict[str, Any]] = report["unparseable_spans"]

        for item in iter_json_objects(path, spans.append):
            value = item.value
            if not isinstance(value, dict):
                spans.append(_span(item.start, item.end, "top_level_not_object"))
                continue
            if is_schema(value):
                report["schema_lines"] += 1
                report["projected_output_bytes"] += len(item.raw) + 1
                continue

            report["objects"] += 1
            has_id = "id" in value and value["id"] is not None
            if not has_id:
                report["missing_id_objects"] += 1
            else:
                report["id_objects"] += 1
                seen_ids_in_file.add(canonical_id(value["id"]))

            if dedup_mode == "id":
                if not has_id:
                    continue
                dedup_key = canonical_id(value["id"])
            else:
                dedup_key = content_key(value)
                assert seen_contents_in_file is not None
                seen_contents_in_file.add(dedup_key)

            key = selection_key(value, sequence)
            record_bytes = len(item.raw) + 1
            previous = winners.get(dedup_key)
            candidate = (key[0], key[1], key[2], file_index, record_bytes)
            if previous is None or candidate[:2] > previous[:2]:
                if previous is not None:
                    previous_path = files[previous[3]].relative_to(input_dir).as_posix()
                    reports[previous_path]["projected_output_bytes"] -= previous[4]
                winners[dedup_key] = candidate
                report["projected_output_bytes"] += record_bytes
            sequence += 1

        report["unique_ids"] = len(seen_ids_in_file)
        if seen_contents_in_file is not None:
            report["unique_contents"] = len(seen_contents_in_file)
            report["content_duplicates_dropped"] = (
                report["objects"] - report["unique_contents"]
            )
            report["dup_ratio"] = (
                report["content_duplicates_dropped"] / report["objects"]
                if report["objects"]
                else 0.0
            )
        size_after = path.stat().st_size
        report["input_bytes_after_scan"] = size_after
        report["input_changed_during_scan"] = size_after != report["input_bytes"]

    selected_by_file: dict[int, int] = defaultdict(int)
    for winner in winners.values():
        selected_by_file[winner[3]] += 1
    for file_index, path in enumerate(files):
        report = reports[path.relative_to(input_dir).as_posix()]
        report["winners_selected"] = selected_by_file[file_index]
        if dedup_mode == "id":
            report["duplicates_dropped"] = report["id_objects"] - report["winners_selected"]
            report["dup_ratio"] = (
                report["duplicates_dropped"] / report["id_objects"]
                if report["id_objects"]
                else 0.0
            )
        else:
            report["duplicates_dropped"] = None
    return winners


def _emit_tier(
    input_dir: Path,
    output_dir: Path,
    files: Sequence[Path],
    reports: dict[str, dict[str, Any]],
    winners: dict[str, Winner],
    dedup_mode: str,
) -> None:
    """Pass 2: emit schema objects and selected records in source order."""

    sequence = 0
    for file_index, path in enumerate(files):
        relative = path.relative_to(input_dir)
        report = reports[relative.as_posix()]
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        output_lines = 0
        emitted_records = 0
        with destination.open("xb") as output:
            for item in iter_json_objects(path):
                value = item.value
                if not isinstance(value, dict):
                    continue
                if is_schema(value):
                    output.write(item.raw)
                    output.write(b"\n")
                    output_lines += 1
                    continue
                if dedup_mode == "id":
                    if "id" not in value or value["id"] is None:
                        continue
                    dedup_key = canonical_id(value["id"])
                else:
                    dedup_key = content_key(value)
                winner = winners.get(dedup_key)
                if winner is not None and winner[2] == sequence and winner[3] == file_index:
                    output.write(item.raw)
                    output.write(b"\n")
                    output_lines += 1
                    emitted_records += 1
                sequence += 1
        report["output_lines"] = output_lines
        report["output_bytes"] = destination.stat().st_size
        if emitted_records != report["winners_selected"]:
            raise RuntimeError(
                f"emit mismatch for {relative}: selected {report['winners_selected']}, "
                f"emitted {emitted_records}"
            )


def verify_outputs(
    output_dir: Path,
    file_reports: Sequence[dict[str, Any]],
    dedup_mode: str = "id",
) -> dict[str, Any]:
    """Verify clean JSONL, expected counts, and tier-wide key uniqueness."""

    failures: list[dict[str, Any]] = []
    tier_keys: dict[str, set[str]] = defaultdict(set)
    checked_files = 0
    checked_data_lines = 0

    for report in file_reports:
        relative = Path(report["path"])
        path = output_dir / relative
        checked_files += 1
        data_lines = 0
        schema_lines = 0
        total_lines = 0
        try:
            handle = path.open("rb")
        except OSError as exc:
            failures.append({"path": report["path"], "error": f"cannot open output: {exc}"})
            continue
        with handle:
            for line_number, raw_line in enumerate(handle, 1):
                total_lines += 1
                if not raw_line.endswith(b"\n"):
                    failures.append({
                        "path": report["path"],
                        "line": line_number,
                        "error": "line is not newline-terminated",
                    })
                try:
                    value = json.loads(raw_line)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    failures.append({
                        "path": report["path"],
                        "line": line_number,
                        "error": f"invalid JSON: {exc}",
                    })
                    continue
                if not isinstance(value, dict):
                    failures.append({
                        "path": report["path"],
                        "line": line_number,
                        "error": "top-level JSON value is not an object",
                    })
                    continue
                if is_schema(value):
                    schema_lines += 1
                    continue
                if dedup_mode == "id" and ("id" not in value or value["id"] is None):
                    failures.append({
                        "path": report["path"],
                        "line": line_number,
                        "error": "data object has no id",
                    })
                    continue
                data_lines += 1
                dedup_key = (
                    canonical_id(value["id"])
                    if dedup_mode == "id"
                    else content_key(value)
                )
                if dedup_key in tier_keys[report["tier"]]:
                    key_name = "id" if dedup_mode == "id" else "content"
                    failures.append({
                        "path": report["path"],
                        "line": line_number,
                        "error": f"duplicate {key_name} in tier {report['tier']}: {dedup_key}",
                    })
                tier_keys[report["tier"]].add(dedup_key)

        checked_data_lines += data_lines
        if data_lines != report["winners_selected"]:
            failures.append({
                "path": report["path"],
                "error": (
                    f"data line count {data_lines} does not equal selected winner count "
                    f"{report['winners_selected']}"
                ),
            })
        if schema_lines != report["schema_lines"]:
            failures.append({
                "path": report["path"],
                "error": f"schema line count {schema_lines} does not equal expected {report['schema_lines']}",
            })
        if total_lines != data_lines + schema_lines:
            failures.append({
                "path": report["path"],
                "error": "one or more output lines were neither valid schema nor valid data objects",
            })

    return {
        "ok": not failures,
        "checked_files": checked_files,
        "checked_data_lines": checked_data_lines,
        "failures": failures,
    }


def peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; macOS reports bytes.
    return int(value if sys.platform == "darwin" else value * 1024)


def _build_summary(
    file_reports: Sequence[dict[str, Any]],
    elapsed: float,
    dedup_mode: str,
) -> dict[str, Any]:
    objects = sum(item["objects"] for item in file_reports)
    id_objects = sum(item["id_objects"] for item in file_reports)
    winners = sum(item["winners_selected"] for item in file_reports)
    duplicates = (id_objects - winners) if dedup_mode == "id" else None
    content_duplicates = (objects - winners) if dedup_mode == "content" else None
    return {
        "files": len(file_reports),
        "objects": objects,
        "id_objects": id_objects,
        "unique_ids": winners if dedup_mode == "id" else None,
        "duplicates_dropped": duplicates,
        "duplicate_ratio": (
            duplicates / id_objects if dedup_mode == "id" and id_objects else 0.0
        ),
        "unique_contents": winners if dedup_mode == "content" else None,
        "content_duplicates_dropped": content_duplicates,
        "dup_ratio": (
            content_duplicates / objects
            if dedup_mode == "content" and objects
            else 0.0
        ),
        "projected_output_bytes": sum(item["projected_output_bytes"] for item in file_reports),
        "schema_lines": sum(item["schema_lines"] for item in file_reports),
        "missing_id_objects": sum(item["missing_id_objects"] for item in file_reports),
        "unparseable_spans": sum(len(item["unparseable_spans"]) for item in file_reports),
        "unparseable_bytes": sum(
            span["length_bytes"]
            for item in file_reports
            for span in item["unparseable_spans"]
        ),
        "input_files_changed_during_scan": sum(
            bool(item["input_changed_during_scan"]) for item in file_reports
        ),
        "elapsed_seconds": round(elapsed, 3),
        "peak_rss_bytes": peak_rss_bytes(),
    }


def recover(
    input_dir: Path,
    output_dir: Path,
    *,
    count_only: bool = False,
    verify: bool = False,
    allow_live_read: bool = False,
    dedup_mode: str = "id",
) -> dict[str, Any]:
    input_dir, output_dir = validate_paths(input_dir, output_dir, allow_live_read)
    if count_only and verify:
        raise ValueError("--verify cannot be combined with --count-only")
    if dedup_mode not in DEDUP_MODES:
        raise ValueError(f"dedup_mode must be one of: {', '.join(DEDUP_MODES)}")
    files = discover_files(input_dir)
    if not files:
        raise ValueError(f"no .jsonl files found under {input_dir}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    reports: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        relative = path.relative_to(input_dir)
        reports[relative.as_posix()] = _empty_file_report(relative, path)
        grouped[tier_for(relative)].append(path)

    for tier in sorted(grouped):
        tier_files = grouped[tier]
        winners = _scan_tier(input_dir, tier_files, reports, dedup_mode)
        if not count_only:
            _emit_tier(input_dir, output_dir, tier_files, reports, winners, dedup_mode)
        del winners

    ordered_reports = [reports[path.relative_to(input_dir).as_posix()] for path in files]
    result: dict[str, Any] = {
        "version": 2,
        "mode": "count-only" if count_only else "recover",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "live_read": input_dir == LIVE_MEMORY_DIR,
        "dedup_mode": dedup_mode,
        "volatile_fields": sorted(VOLATILE) if dedup_mode == "content" else None,
        "timestamp_order": list(TIMESTAMP_FIELDS),
        "files": ordered_reports,
    }
    if verify:
        result["verification"] = verify_outputs(output_dir, ordered_reports, dedup_mode)
    result["summary"] = _build_summary(
        ordered_reports, time.monotonic() - started, dedup_mode
    )

    report_path = output_dir / REPORT_NAME
    with report_path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    result["report_path"] = str(report_path)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--allow-live-read",
        action="store_true",
        help="allow read-only scanning when --input-dir is the live modules/memory tree",
    )
    parser.add_argument("--count-only", action="store_true", help="run pass 1 and write only the report")
    parser.add_argument("--verify", action="store_true", help="verify all emitted JSONL after recovery")
    parser.add_argument(
        "--dedup-mode",
        choices=DEDUP_MODES,
        default="id",
        help="deduplicate tier-wide by record id (default) or stable content",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = recover(
            args.input_dir,
            args.output_dir,
            count_only=args.count_only,
            verify=args.verify,
            allow_live_read=args.allow_live_read,
            dedup_mode=args.dedup_mode,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"recover_blobs_v2: error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("verification", {}).get("ok") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
