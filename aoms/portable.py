"""Versioned, hash-verified portable exports for AOMS v2."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aoms.contracts import MemoryRecord
from aoms.receipts import RecallReceipt
from aoms.repositories.sqlite import LATEST_SCHEMA_VERSION, SQLiteMemoryRepository
from aoms.version import __version__

EXPORT_FORMAT = "aoms-portable-export"
EXPORT_FORMAT_VERSION = 1
RECORDS_FILE = "records.jsonl"
RECEIPTS_FILE = "receipts.jsonl"
MANIFEST_FILE = "manifest.json"


class PortableExportError(ValueError):
    """The portable bundle is incomplete, unsupported, or has been modified."""


@dataclass(frozen=True, slots=True)
class ExportResult:
    destination: Path
    records: int
    receipts: int


@dataclass(frozen=True, slots=True)
class RestoreResult:
    records: int
    receipts: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_jsonl(path: Path, rows: Iterator[str]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(row.rstrip("\n"))
            handle.write("\n")
            count += 1
    return count


def _file_entry(path: Path, records: int) -> dict[str, Any]:
    return {
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "records": records,
    }


async def export_bundle(
    repository: SQLiteMemoryRepository, destination: str | Path
) -> ExportResult:
    """Export every canonical record and receipt from one SQLite snapshot."""

    await repository.initialize()
    destination = Path(destination).expanduser().resolve()
    if destination.exists() and not destination.is_dir():
        raise PortableExportError(
            f"export destination is not a directory: {destination}"
        )
    if destination.exists() and any(destination.iterdir()):
        raise PortableExportError(f"export destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    records_path = destination / RECORDS_FILE
    receipts_path = destination / RECEIPTS_FILE
    with sqlite3.connect(repository.db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        record_count = _write_jsonl(
            records_path,
            (
                str(row["record_json"])
                for row in connection.execute(
                    "SELECT record_json FROM memories ORDER BY id"
                )
            ),
        )
        receipt_count = _write_jsonl(
            receipts_path,
            (
                str(row["receipt_json"])
                for row in connection.execute(
                    "SELECT receipt_json FROM recall_receipts "
                    "ORDER BY created_at, receipt_id"
                )
            ),
        )
        schema_row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()
    manifest = {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "aoms_version": __version__,
        "database_schema_version": int(schema_row[0]),
        "files": {
            RECORDS_FILE: _file_entry(records_path, record_count),
            RECEIPTS_FILE: _file_entry(receipts_path, receipt_count),
        },
    }
    (destination / MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return ExportResult(destination, record_count, receipt_count)


def _load_manifest(source: Path) -> dict[str, Any]:
    manifest_path = source / MANIFEST_FILE
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PortableExportError(f"manifest is missing: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise PortableExportError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PortableExportError("manifest must be a JSON object")
    if manifest.get("format") != EXPORT_FORMAT:
        raise PortableExportError("manifest format is not an AOMS portable export")
    if manifest.get("format_version") != EXPORT_FORMAT_VERSION:
        raise PortableExportError(
            f"unsupported export format version: {manifest.get('format_version')!r}"
        )
    if not isinstance(manifest.get("files"), dict):
        raise PortableExportError("manifest files section is missing")
    return manifest


def _validate_file(source: Path, name: str, expected: Any) -> Path:
    if not isinstance(expected, dict):
        raise PortableExportError(f"manifest entry for {name} is invalid")
    path = source / name
    if not path.is_file():
        raise PortableExportError(f"export file is missing: {name}")
    actual_hash = _sha256(path)
    if actual_hash != expected.get("sha256"):
        raise PortableExportError(
            f"hash mismatch for {name}: expected {expected.get('sha256')}, "
            f"got {actual_hash}"
        )
    if path.stat().st_size != expected.get("bytes"):
        raise PortableExportError(f"byte count mismatch for {name}")
    return path


def _validate_jsonl(path: Path, model: type[MemoryRecord | RecallReceipt]) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise PortableExportError(
                    f"blank line in {path.name} at line {line_number}"
                )
            try:
                model.model_validate_json(line)
            except (TypeError, ValueError) as exc:
                raise PortableExportError(
                    f"invalid {path.name} record at line {line_number}: {exc}"
                ) from exc
            count += 1
    return count


def _iter_records(path: Path) -> Iterator[MemoryRecord]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            yield MemoryRecord.model_validate_json(line)


def _iter_receipts(path: Path) -> Iterator[RecallReceipt]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            yield RecallReceipt.model_validate_json(line)


async def restore_bundle(
    repository: SQLiteMemoryRepository,
    source: str | Path,
    *,
    batch_size: int = 500,
) -> RestoreResult:
    """Validate a complete bundle before restoring it into an empty store."""

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    source = Path(source).expanduser().resolve()
    if not source.is_dir():
        raise PortableExportError(f"export source is not a directory: {source}")
    manifest = _load_manifest(source)
    files = manifest["files"]
    records_path = _validate_file(source, RECORDS_FILE, files.get(RECORDS_FILE))
    receipts_path = _validate_file(source, RECEIPTS_FILE, files.get(RECEIPTS_FILE))
    record_count = _validate_jsonl(records_path, MemoryRecord)
    receipt_count = _validate_jsonl(receipts_path, RecallReceipt)
    if record_count != files[RECORDS_FILE].get("records"):
        raise PortableExportError(f"record count mismatch for {RECORDS_FILE}")
    if receipt_count != files[RECEIPTS_FILE].get("records"):
        raise PortableExportError(f"record count mismatch for {RECEIPTS_FILE}")
    source_schema = manifest.get("database_schema_version")
    if not isinstance(source_schema, int) or source_schema > LATEST_SCHEMA_VERSION:
        raise PortableExportError(
            f"export schema {source_schema!r} is newer than supported schema "
            f"{LATEST_SCHEMA_VERSION}"
        )

    await repository.initialize()
    with sqlite3.connect(repository.db_path) as connection:
        existing = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        existing_receipts = connection.execute(
            "SELECT COUNT(*) FROM recall_receipts"
        ).fetchone()[0]
    if existing or existing_receipts:
        raise PortableExportError(
            "restore target is not empty; choose a new --data-dir to avoid "
            "overwriting data"
        )

    batch: list[MemoryRecord] = []
    for record in _iter_records(records_path):
        batch.append(record)
        if len(batch) == batch_size:
            await repository.store_many_new(batch)
            batch.clear()
    if batch:
        await repository.store_many_new(batch)

    # Receipts are already fully validated. Insert directly so a bundle remains
    # complete even when its historical retention setting differs from this host.
    with sqlite3.connect(repository.db_path) as connection:
        connection.executemany(
            "INSERT INTO recall_receipts("
            "receipt_id, created_at, agent_id, workspace_id, receipt_json"
            ") VALUES (?, ?, ?, ?, ?)",
            (
                (
                    receipt.receipt_id,
                    receipt.created_at.isoformat(),
                    receipt.agent_id,
                    receipt.workspace_id,
                    receipt.model_dump_json(),
                )
                for receipt in _iter_receipts(receipts_path)
            ),
        )
        connection.commit()
    return RestoreResult(record_count, receipt_count)


__all__ = [
    "EXPORT_FORMAT",
    "EXPORT_FORMAT_VERSION",
    "MANIFEST_FILE",
    "ExportResult",
    "PortableExportError",
    "RestoreResult",
    "export_bundle",
    "restore_bundle",
]
