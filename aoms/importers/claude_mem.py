"""Fixture-pinned reader for claude-mem's local SQLite store."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aoms.contracts import MemoryKind, MemoryRecord, Provenance, Scope

from .base import ImportContext, ImportPreview, analyze_records, content_id


CLAUDE_MEM_SCHEMA_VERSION = 49
CLAUDE_MEM_UPSTREAM_VERSION = "13.15.3"
CLAUDE_MEM_SOURCE_COMMIT = "e2d1df569a8f04075d40e92461128ece7cf04c82"


class ClaudeMemSchemaError(ValueError):
    """Raised before conversion when a claude-mem schema is not pinned."""


class ClaudeMemAdapter:
    """Read observations and summaries from claude-mem schema version 49."""

    name = "claude-mem"
    version = "claude-mem-sqlite-v49"

    _REQUIRED_COLUMNS: Mapping[str, frozenset[str]] = {
        "observations": frozenset(
            {
                "id",
                "memory_session_id",
                "project",
                "text",
                "type",
                "title",
                "subtitle",
                "facts",
                "narrative",
                "concepts",
                "files_read",
                "files_modified",
                "prompt_number",
                "created_at",
                "created_at_epoch",
            }
        ),
        "session_summaries": frozenset(
            {
                "id",
                "memory_session_id",
                "project",
                "request",
                "investigated",
                "learned",
                "completed",
                "next_steps",
                "files_read",
                "files_edited",
                "notes",
                "prompt_number",
                "created_at",
                "created_at_epoch",
            }
        ),
        "schema_versions": frozenset({"version", "applied_at"}),
    }

    def __init__(self, context: ImportContext):
        self.context = context

    def detect(self, path: str | Path) -> bool:
        try:
            database = self._database_path(path)
            with closing(self._connect(database)) as connection:
                tables = self._tables(connection)
            return {"schema_versions", "observations", "session_summaries"}.issubset(
                tables
            )
        except (OSError, sqlite3.Error, ValueError):
            return False

    def preview(self, path: str | Path) -> ImportPreview:
        database = self._database_path(path)
        records = tuple(self.convert(database))
        projects = tuple(
            sorted({str(record.metadata["project"]) for record in records})
        )
        duplicates, warnings = analyze_records(records)
        mapping = self._workspace_mapping(projects)
        return ImportPreview(
            adapter=self.name,
            adapter_version=self.version,
            source_path=database,
            source_items=len(records),
            records=records,
            duplicate_groups=duplicates,
            secret_warnings=warnings,
            scope=self.context.scope,
            workspace_mapping=mapping,
        )

    def convert(self, path: str | Path) -> Iterator[MemoryRecord]:
        database = self._database_path(path)
        with closing(self._validated_connection(database)) as connection:
            # Keep all source rows on one SQLite read snapshot. BEGIN is read-only
            # under query_only and avoids a live claude-mem writer splitting a preview.
            connection.execute("BEGIN")
            projects = self._projects(connection)
            workspace_mapping = self._workspace_mapping(projects)
            observations = connection.execute(
                """
                SELECT id, memory_session_id, project, text, type, title, subtitle,
                       facts, narrative, concepts, files_read, files_modified,
                       prompt_number, created_at, created_at_epoch
                FROM observations ORDER BY id
                """
            ).fetchall()
            summaries = connection.execute(
                """
                SELECT id, memory_session_id, project, request, investigated, learned,
                       completed, next_steps, files_read, files_edited, notes,
                       prompt_number, created_at, created_at_epoch
                FROM session_summaries ORDER BY id
                """
            ).fetchall()

        for row in observations:
            yield self._observation_record(database, row, workspace_mapping)
        for row in summaries:
            yield self._summary_record(database, row, workspace_mapping)

    @staticmethod
    def _database_path(path: str | Path) -> Path:
        selected = Path(path).expanduser().resolve()
        database = selected / "claude-mem.db" if selected.is_dir() else selected
        if not database.is_file():
            raise ValueError(
                f"claude-mem database not found: {database} "
                "(expected a claude-mem.db file or its containing directory)"
            )
        return database

    @staticmethod
    def _connect(database: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"{database.as_uri()}?mode=ro", uri=True, timeout=5.0
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    def _validated_connection(self, database: Path) -> sqlite3.Connection:
        connection = self._connect(database)
        try:
            self._validate_schema(connection, database)
        except Exception:
            connection.close()
            raise
        return connection

    def _validate_schema(self, connection: sqlite3.Connection, database: Path) -> None:
        tables = self._tables(connection)
        missing_tables = sorted(set(self._REQUIRED_COLUMNS) - tables)
        if missing_tables:
            raise ClaudeMemSchemaError(
                f"unsupported claude-mem database at {database}: missing table(s) "
                f"{', '.join(missing_tables)}; expected claude-mem schema "
                f"{CLAUDE_MEM_SCHEMA_VERSION}"
            )
        row = connection.execute(
            "SELECT MAX(version) AS version FROM schema_versions"
        ).fetchone()
        actual = row["version"] if row is not None else None
        if actual != CLAUDE_MEM_SCHEMA_VERSION:
            raise ClaudeMemSchemaError(
                f"unsupported claude-mem schema version {actual!r}; this adapter is "
                f"pinned to version {CLAUDE_MEM_SCHEMA_VERSION} "
                f"(claude-mem {CLAUDE_MEM_UPSTREAM_VERSION}). Refusing to guess. "
                "Use a matching read-only export or a newer cortex-mem adapter."
            )
        for table, required in self._REQUIRED_COLUMNS.items():
            columns = {
                str(info["name"])
                for info in connection.execute(f'PRAGMA table_info("{table}")')
            }
            missing = sorted(required - columns)
            if missing:
                raise ClaudeMemSchemaError(
                    f"claude-mem schema {actual} at {database} is missing expected "
                    f"column(s) in {table}: {', '.join(missing)}. Refusing to guess."
                )

    @staticmethod
    def _tables(connection: sqlite3.Connection) -> set[str]:
        return {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }

    @staticmethod
    def _projects(connection: sqlite3.Connection) -> tuple[str, ...]:
        return tuple(
            str(row["project"])
            for row in connection.execute(
                """
                SELECT project FROM observations
                UNION
                SELECT project FROM session_summaries
                ORDER BY project
                """
            )
        )

    def _workspace_mapping(self, projects: Sequence[str]) -> dict[str, str]:
        if self.context.scope is Scope.USER_GLOBAL:
            return {project: Scope.USER_GLOBAL.value for project in projects}
        if self.context.workspace_id:
            return {project: self.context.workspace_id for project in projects}
        return {project: self._workspace_id(project) for project in projects}

    @staticmethod
    def _workspace_id(project: str) -> str:
        normalized = posixpath.normpath(project.replace("\\", "/"))
        name = normalized.rsplit("/", 1)[-1]
        slug = re.sub(r"[^a-z0-9._-]+", "-", name.casefold()).strip("-.")
        digest = hashlib.sha256(normalized.casefold().encode("utf-8")).hexdigest()[:8]
        return f"{slug or 'claude-mem-project'}-{digest}"

    def _observation_record(
        self,
        database: Path,
        row: sqlite3.Row,
        workspace_mapping: Mapping[str, str],
    ) -> MemoryRecord:
        fields = [
            ("title", row["title"]),
            ("subtitle", row["subtitle"]),
            ("narrative", row["narrative"]),
            ("text", row["text"]),
        ]
        content_parts = [
            f"{label.title()}: {str(value).strip()}"
            for label, value in fields
            if value is not None and str(value).strip()
        ]
        facts = self._list_value(row["facts"])
        if facts:
            content_parts.append("Facts:\n" + "\n".join(f"- {item}" for item in facts))
        content = "\n\n".join(content_parts) or f"claude-mem observation {row['id']}"
        project = str(row["project"])
        created_at = self._timestamp(row["created_at"], row["created_at_epoch"])
        observation_type = str(row["type"] or "change").casefold()
        metadata = {
            "source_format": "claude-mem-sqlite",
            "claude_mem_item": "observation",
            "claude_mem_id": int(row["id"]),
            "session_id": str(row["memory_session_id"]),
            "project": project,
            "observation_type": observation_type,
            "prompt_number": row["prompt_number"],
            "concepts": self._list_value(row["concepts"]),
            "files_read": self._list_value(row["files_read"]),
            "files_modified": self._list_value(row["files_modified"]),
        }
        return self._record(
            database=database,
            native_type="observation",
            native_id=int(row["id"]),
            project=project,
            workspace_mapping=workspace_mapping,
            content=content,
            kind=self._observation_kind(observation_type),
            created_at=created_at,
            metadata=metadata,
            tags=[observation_type, *metadata["concepts"]],
        )

    def _summary_record(
        self,
        database: Path,
        row: sqlite3.Row,
        workspace_mapping: Mapping[str, str],
    ) -> MemoryRecord:
        labels = (
            ("Request", "request"),
            ("Investigated", "investigated"),
            ("Learned", "learned"),
            ("Completed", "completed"),
            ("Next steps", "next_steps"),
            ("Notes", "notes"),
        )
        content = (
            "\n\n".join(
                f"{label}: {str(row[key]).strip()}"
                for label, key in labels
                if row[key] is not None and str(row[key]).strip()
            )
            or f"claude-mem session summary {row['id']}"
        )
        project = str(row["project"])
        created_at = self._timestamp(row["created_at"], row["created_at_epoch"])
        metadata = {
            "source_format": "claude-mem-sqlite",
            "claude_mem_item": "session-summary",
            "claude_mem_id": int(row["id"]),
            "session_id": str(row["memory_session_id"]),
            "project": project,
            "prompt_number": row["prompt_number"],
            "files_read": self._list_value(row["files_read"]),
            "files_edited": self._list_value(row["files_edited"]),
        }
        return self._record(
            database=database,
            native_type="session-summary",
            native_id=int(row["id"]),
            project=project,
            workspace_mapping=workspace_mapping,
            content=content,
            kind=MemoryKind.EPISODE,
            created_at=created_at,
            metadata=metadata,
            tags=["claude-mem-summary"],
        )

    def _record(
        self,
        *,
        database: Path,
        native_type: str,
        native_id: int,
        project: str,
        workspace_mapping: Mapping[str, str],
        content: str,
        kind: MemoryKind,
        created_at: datetime,
        metadata: dict[str, Any],
        tags: list[str],
    ) -> MemoryRecord:
        source_key = f"{native_type}:{project}:{native_id}"
        workspace_id = (
            workspace_mapping[project]
            if self.context.scope is Scope.WORKSPACE
            else None
        )
        return MemoryRecord(
            id=content_id(self.version, source_key, content),
            kind=kind,
            content=content,
            tags=tags,
            scope=self.context.scope,
            scope_workspace_id=workspace_id,
            created_by_agent_id=self.context.actor_id,
            provenance=Provenance(
                source=database.as_posix(),
                record_type=native_type,
                details={
                    "file_path": database.as_posix(),
                    "format": "claude-mem-sqlite",
                    "schema_version": CLAUDE_MEM_SCHEMA_VERSION,
                    "imported_at": self.context.imported_at.isoformat(),
                    "adapter_version": self.version,
                    "source_item_id": native_id,
                    "project": project,
                },
            ),
            created_at=created_at,
            updated_at=created_at,
            metadata=metadata,
        )

    @staticmethod
    def _observation_kind(observation_type: str) -> MemoryKind:
        return {
            "decision": MemoryKind.DECISION,
            "discovery": MemoryKind.FACT,
            "bugfix": MemoryKind.FAILURE,
            "feature": MemoryKind.EPISODE,
            "refactor": MemoryKind.EPISODE,
            "change": MemoryKind.EPISODE,
        }.get(observation_type, MemoryKind.FACT)

    @staticmethod
    def _timestamp(value: Any, epoch: Any) -> datetime:
        if value:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                pass
        numeric = float(epoch)
        if abs(numeric) > 10_000_000_000:
            numeric /= 1_000
        return datetime.fromtimestamp(numeric, tz=timezone.utc)

    @staticmethod
    def _list_value(value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return [item.strip() for item in value.split(",") if item.strip()]
        else:
            parsed = value
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [str(parsed).strip()] if str(parsed).strip() else []
