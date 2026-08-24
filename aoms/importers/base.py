"""Safe, source-aware import contracts and execution orchestration."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from aoms.contracts import MemoryRecord, Scope
from aoms.repositories.base import MemoryRepository


@dataclass(frozen=True, slots=True)
class ImportContext:
    """Explicit trust decisions shared by all source adapters."""

    scope: Scope
    imported_at: datetime
    actor_id: str = "source-importer"
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        if self.scope not in {Scope.WORKSPACE, Scope.USER_GLOBAL}:
            raise ValueError("imports support only workspace or user-global scope")
        if self.imported_at.tzinfo is None:
            raise ValueError("imported_at must be timezone-aware")
        if not self.actor_id.strip():
            raise ValueError("actor_id must not be empty")
        if self.workspace_id is not None and not self.workspace_id.strip():
            raise ValueError("workspace_id must not be empty")

    @classmethod
    def now(
        cls,
        scope: Scope,
        *,
        actor_id: str = "source-importer",
        workspace_id: str | None = None,
    ) -> ImportContext:
        return cls(
            scope=scope,
            imported_at=datetime.now(timezone.utc),
            actor_id=actor_id,
            workspace_id=workspace_id,
        )


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """Records whose normalized content is identical before import."""

    fingerprint: str
    record_ids: tuple[str, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SecretWarning:
    """A possible credential finding with the credential value omitted."""

    record_id: str
    source: str
    pattern: str
    line_number: int


@dataclass(frozen=True, slots=True)
class ImportPreview:
    """Complete, read-only import proposal returned before any commit."""

    adapter: str
    adapter_version: str
    source_path: Path
    source_items: int
    records: tuple[MemoryRecord, ...]
    duplicate_groups: tuple[DuplicateGroup, ...] = ()
    secret_warnings: tuple[SecretWarning, ...] = ()
    scope: Scope = Scope.WORKSPACE
    workspace_mapping: Mapping[str, str] = field(default_factory=dict)

    @property
    def proposed_memories(self) -> int:
        return len(self.records)

    @property
    def possible_secrets_flagged(self) -> int:
        return len(self.secret_warnings)

    def summary(self) -> str:
        return (
            f"{self.source_items} source items \u2192 {self.proposed_memories} "
            f"proposed memories; {len(self.duplicate_groups)} duplicate groups; "
            f"{self.possible_secrets_flagged} possible secrets flagged; "
            f"scope choice: {self.scope.value}; no source files modified"
        )


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Dry-run or committed outcome; execution is opt-in."""

    preview: ImportPreview
    executed: bool = False
    records_committed: int = 0
    records_created: int = 0
    records_updated: int = 0


@runtime_checkable
class SourceAdapter(Protocol):
    """Stable boundary for versioned, fixture-tested source readers."""

    name: str
    version: str

    def detect(self, path: str | Path) -> bool: ...

    def preview(self, path: str | Path) -> ImportPreview: ...

    def convert(self, path: str | Path) -> Iterator[MemoryRecord]: ...


# These patterns intentionally favor warnings over ingestion-time mutation. Values are
# never included in reports. They cover the common open-source scanner categories:
# private-key blocks, named API/token assignments, JWTs, GitHub tokens, and AWS keys.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    (
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    (
        "model-api-key",
        re.compile(r"\bsk-(?:(?:proj|ant|svcacct)-)?[A-Za-z0-9_-]{16,}\b"),
    ),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "named-secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret[_-]?key|password)\b"
            r"\s*(?::|=)\s*['\"]?[A-Za-z0-9_./+\-=]{12,}"
        ),
    ),
    (
        "bearer-token",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_./+\-=]{16,}"),
    ),
)


def content_id(adapter: str, source_key: str, content: str) -> str:
    """Return a deterministic ID derived from source identity and content."""

    material = f"{adapter}\0{source_key}\0{content}".encode("utf-8")
    return "import-" + hashlib.sha256(material).hexdigest()


def normalized_content(content: object) -> str:
    text = (
        content
        if isinstance(content, str)
        else json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    )
    return " ".join(text.casefold().split())


def analyze_records(
    records: tuple[MemoryRecord, ...],
) -> tuple[tuple[DuplicateGroup, ...], tuple[SecretWarning, ...]]:
    """Find exact normalized duplicates and possible secrets without exposing values."""

    grouped: dict[str, list[MemoryRecord]] = defaultdict(list)
    warnings: list[SecretWarning] = []
    for record in records:
        content = normalized_content(record.content)
        fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
        grouped[fingerprint].append(record)
        display = (
            record.content
            if isinstance(record.content, str)
            else record.model_dump_json()
        )
        for line_number, line in enumerate(display.splitlines(), 1):
            for label, pattern in _SECRET_PATTERNS:
                if pattern.search(line):
                    warnings.append(
                        SecretWarning(
                            record_id=record.id,
                            source=record.provenance.source,
                            pattern=label,
                            line_number=line_number,
                        )
                    )

    duplicates = tuple(
        DuplicateGroup(
            fingerprint=fingerprint,
            record_ids=tuple(record.id for record in items),
            sources=tuple(record.provenance.source for record in items),
        )
        for fingerprint, items in sorted(grouped.items())
        if len(items) > 1
    )
    return duplicates, tuple(warnings)


async def run_import(
    adapter: SourceAdapter,
    path: str | Path,
    *,
    execute: bool = False,
    repository: MemoryRepository | None = None,
) -> ImportResult:
    """Preview by default; commit the exact preview only when explicitly requested."""

    preview = adapter.preview(path)
    if not execute:
        return ImportResult(preview=preview)
    if repository is None:
        raise ValueError("repository is required when execute=True")

    await repository.initialize()
    existing = 0
    for record in preview.records:
        if await repository.get(record.id) is not None:
            existing += 1
    await repository.store_many(preview.records)
    return ImportResult(
        preview=preview,
        executed=True,
        records_committed=preview.proposed_memories,
        records_created=preview.proposed_memories - existing,
        records_updated=existing,
    )
