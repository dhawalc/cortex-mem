"""Import recovered legacy JSONL tiers into the canonical SQLite store.

Kind mapping is deliberately closed and deterministic:

* episodic ``experience`` -> ``episode``; ``decision`` and ``failure`` retain
  their names; other episodic types fall back to ``episode``.
* semantic ``fact``, ``entity``, and ``relation`` retain their names; other
  semantic types fall back to ``fact``.
* procedural ``skill`` or ``procedure`` -> ``procedure``; ``pattern`` retains
  its name; other procedural types fall back to ``procedure``.

The source path stored in provenance is relative to the selected corpus root.
Schema-header lines are skipped. Record IDs are preserved and repository
storage is an upsert, so repeating an import cannot create duplicates.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aoms.contracts import MemoryKind, MemoryRecord, Provenance, Scope, ScopeContext
from aoms.repositories.base import MemoryRepository

KIND_MAPPING: dict[str, dict[str, MemoryKind]] = {
    "episodic": {
        "experience": MemoryKind.EPISODE,
        "episode": MemoryKind.EPISODE,
        "decision": MemoryKind.DECISION,
        "failure": MemoryKind.FAILURE,
    },
    "semantic": {
        "fact": MemoryKind.FACT,
        "entity": MemoryKind.ENTITY,
        "relation": MemoryKind.RELATION,
    },
    "procedural": {
        "skill": MemoryKind.PROCEDURE,
        "procedure": MemoryKind.PROCEDURE,
        "pattern": MemoryKind.PATTERN,
    },
}

KIND_FALLBACK = {
    "episodic": MemoryKind.EPISODE,
    "semantic": MemoryKind.FACT,
    "procedural": MemoryKind.PROCEDURE,
}

ENVELOPE_FIELDS = {
    "id",
    "ts",
    "tags",
    "weight",
    "_tier",
    "_type",
    "_written_at",
    "_weight_updated_at",
    "_decay_applied_at",
    "_indexed_at",
    "_migrated_at",
    "_source_line",
    "line_number",
}


@dataclass(slots=True)
class ImportIssue:
    source_file: str
    line_number: int
    message: str


@dataclass(slots=True)
class ImportReport:
    files_scanned: int = 0
    records_seen: int = 0
    records_upserted: int = 0
    schema_headers_skipped: int = 0
    issues: list[ImportIssue] = field(default_factory=list)


class JSONLImporter:
    def __init__(
        self,
        repository: MemoryRepository,
        *,
        scope_context: ScopeContext,
        batch_size: int = 500,
        progress: Callable[[Path, ImportReport], None] | None = None,
    ):
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.repository = repository
        self.scope_context = scope_context
        self.batch_size = batch_size
        self.progress = progress

    async def import_directory(self, corpus_root: str | Path) -> ImportReport:
        root = Path(corpus_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"corpus root is not a directory: {root}")

        await self.repository.initialize()
        report = ImportReport()
        for path in sorted(root.rglob("*.jsonl")):
            if not path.is_file():
                continue
            report.files_scanned += 1
            relative = path.relative_to(root)
            tier = relative.parts[0] if len(relative.parts) > 1 else ""
            if tier not in KIND_MAPPING:
                report.issues.append(
                    ImportIssue(
                        relative.as_posix(), 0, f"unsupported tier: {tier or '<none>'}"
                    )
                )
                continue
            await self._import_file(root, path, tier, report)
            if self.progress is not None:
                self.progress(relative, report)
        return report

    async def _import_file(
        self,
        root: Path,
        path: Path,
        tier: str,
        report: ImportReport,
    ) -> None:
        relative = path.relative_to(root).as_posix()
        fallback_time = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        batch: list[MemoryRecord] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, 1):
                if not raw_line.strip():
                    continue
                try:
                    value = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    report.issues.append(
                        ImportIssue(relative, line_number, f"invalid JSON: {exc.msg}")
                    )
                    continue
                if not isinstance(value, dict):
                    report.issues.append(
                        ImportIssue(
                            relative, line_number, "top-level value is not an object"
                        )
                    )
                    continue
                if "schema" in value and "id" not in value:
                    report.schema_headers_skipped += 1
                    continue
                report.records_seen += 1
                try:
                    record = self._convert_record(
                        value,
                        tier=tier,
                        source_file=relative,
                        file_stem=path.stem,
                        fallback_time=fallback_time,
                        scope_context=self.scope_context,
                    )
                except (TypeError, ValueError) as exc:
                    report.issues.append(ImportIssue(relative, line_number, str(exc)))
                    continue
                batch.append(record)
                if len(batch) >= self.batch_size:
                    await self.repository.store_many(batch)
                    report.records_upserted += len(batch)
                    batch.clear()
        if batch:
            await self.repository.store_many(batch)
            report.records_upserted += len(batch)

    @classmethod
    def _convert_record(
        cls,
        value: dict[str, Any],
        *,
        tier: str,
        source_file: str,
        file_stem: str,
        fallback_time: datetime,
        scope_context: ScopeContext,
    ) -> MemoryRecord:
        record_id = value.get("id")
        if record_id is None or not str(record_id).strip():
            raise ValueError("record has no id")

        legacy_type = cls._legacy_type(value, file_stem)
        kind = KIND_MAPPING[tier].get(legacy_type, KIND_FALLBACK[tier])
        created_at = cls._parse_timestamp(value.get("ts")) or fallback_time
        update_candidates = [
            cls._parse_timestamp(value.get(field_name))
            for field_name in (
                "_decay_applied_at",
                "_weight_updated_at",
                "_written_at",
                "ts",
            )
        ]
        updated_at = max(
            (timestamp for timestamp in update_candidates if timestamp is not None),
            default=created_at,
        )
        updated_at = max(updated_at, created_at)

        content = {
            key: item for key, item in value.items() if key not in ENVELOPE_FIELDS
        }
        if not content:
            content = {"legacy_type": legacy_type}
        legacy_metadata = {
            key: item
            for key, item in value.items()
            if key in ENVELOPE_FIELDS
            and key not in {"id", "ts", "tags", "_tier", "_type"}
        }
        metadata: dict[str, Any] = {}
        if legacy_metadata:
            metadata["legacy"] = legacy_metadata

        tags_value = value.get("tags", [])
        if tags_value is None:
            tags: list[str] = []
        elif isinstance(tags_value, list):
            tags = [str(tag) for tag in tags_value]
        else:
            tags = [str(tags_value)]

        return MemoryRecord(
            id=str(record_id),
            kind=kind,
            content=content,
            tags=tags,
            scope=Scope.WORKSPACE,
            scope_workspace_id=scope_context.workspace_id,
            created_by_agent_id=scope_context.agent_id,
            provenance=Provenance(
                source=source_file,
                tier=tier,
                record_type=legacy_type,
                details={"agent_id": scope_context.agent_id},
            ),
            created_at=created_at,
            updated_at=updated_at,
            metadata=metadata,
        )

    @staticmethod
    def _legacy_type(value: dict[str, Any], file_stem: str) -> str:
        explicit = value.get("_type") or value.get("kind")
        if explicit:
            return str(explicit).strip().lower()
        singular = file_stem.lower()
        if singular.endswith("ies"):
            singular = f"{singular[:-3]}y"
        elif singular.endswith("s"):
            singular = singular[:-1]
        return singular

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            numeric = float(value)
            if not math.isfinite(numeric):
                return None
            if abs(numeric) > 10_000_000_000:
                numeric /= 1_000
            try:
                return datetime.fromtimestamp(numeric, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        if not isinstance(value, str) or not value.strip():
            return None
        text = value.strip()
        try:
            return JSONLImporter._parse_timestamp(float(text))
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


async def import_jsonl_directory(
    corpus_root: str | Path,
    repository: MemoryRepository,
    *,
    scope_context: ScopeContext,
) -> ImportReport:
    """Convenience entry point for programmatic fixture or reviewed imports."""

    return await JSONLImporter(
        repository, scope_context=scope_context
    ).import_directory(corpus_root)
