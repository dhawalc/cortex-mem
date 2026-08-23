"""SQLite/WAL repository for canonical AOMS records.

The implementation uses the standard-library ``sqlite3`` driver and runs each
short database operation with ``asyncio.to_thread``. This keeps the public API
async-friendly without introducing an additional runtime dependency, while a
fresh connection per operation avoids sharing SQLite connections across worker
threads. WAL mode and a busy timeout allow concurrent readers and serialized
writes.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Scope,
    SearchHit,
    SearchRequest,
    SearchResult,
)

LATEST_SCHEMA_VERSION = 1

MIGRATIONS: dict[int, str] = {
    1: """
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            scope TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            record_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
        CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope);
        CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at DESC);
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            id UNINDEXED,
            content,
            tags,
            kind,
            tokenize = 'unicode61'
        );
    """,
}


class SQLiteMemoryRepository:
    """Store canonical records in a portable SQLite database with FTS5."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if not self._initialized:
                await asyncio.to_thread(self._initialize_sync)
                self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_sync(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                row["version"]
                for row in connection.execute("SELECT version FROM schema_version").fetchall()
            }
            for version in sorted(MIGRATIONS):
                if version in applied:
                    continue
                connection.executescript(MIGRATIONS[version])
                connection.execute(
                    "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(timezone.utc).isoformat()),
                )
            connection.commit()

    async def schema_version(self) -> int:
        await self.initialize()
        return await asyncio.to_thread(self._schema_version_sync)

    def _schema_version_sync(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_version"
            ).fetchone()
        return int(row["version"])

    async def store(self, record: MemoryRecord) -> MemoryRecord:
        await self.initialize()
        await asyncio.to_thread(self._store_many_sync, [record])
        return record

    async def store_many(self, records: Sequence[MemoryRecord]) -> list[MemoryRecord]:
        materialized = list(records)
        if not materialized:
            return []
        await self.initialize()
        await asyncio.to_thread(self._store_many_sync, materialized)
        return materialized

    def _store_many_sync(self, records: Sequence[MemoryRecord]) -> None:
        with self._connect() as connection:
            for record in records:
                serialized = record.model_dump_json()
                content_text = (
                    record.content
                    if isinstance(record.content, str)
                    else json.dumps(record.content, ensure_ascii=False, sort_keys=True)
                )
                connection.execute(
                    """
                    INSERT INTO memories(id, kind, scope, created_at, updated_at, record_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        kind = excluded.kind,
                        scope = excluded.scope,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        record_json = excluded.record_json
                    """,
                    (
                        record.id,
                        record.kind.value,
                        record.scope.value,
                        record.created_at.isoformat(),
                        record.updated_at.isoformat(),
                        serialized,
                    ),
                )
                connection.execute("DELETE FROM memories_fts WHERE id = ?", (record.id,))
                connection.execute(
                    "INSERT INTO memories_fts(id, content, tags, kind) VALUES (?, ?, ?, ?)",
                    (record.id, content_text, " ".join(record.tags), record.kind.value),
                )
            connection.commit()

    async def get(self, record_id: str) -> MemoryRecord | None:
        await self.initialize()
        return await asyncio.to_thread(self._get_sync, record_id)

    def _get_sync(self, record_id: str) -> MemoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM memories WHERE id = ?", (record_id,)
            ).fetchone()
        return self._record_from_row(row) if row else None

    async def list(
        self,
        *,
        kinds: list[MemoryKind] | None = None,
        scopes: list[Scope] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if offset < 0:
            raise ValueError("offset must not be negative")
        await self.initialize()
        return await asyncio.to_thread(self._list_sync, kinds, scopes, limit, offset)

    def _list_sync(
        self,
        kinds: list[MemoryKind] | None,
        scopes: list[Scope] | None,
        limit: int,
        offset: int,
    ) -> list[MemoryRecord]:
        clauses, parameters = self._filters(kinds=kinds, scopes=scopes, table_alias="")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT record_json FROM memories"
            f"{where} ORDER BY created_at DESC, id ASC LIMIT ? OFFSET ?"
        )
        with self._connect() as connection:
            rows = connection.execute(sql, [*parameters, limit, offset]).fetchall()
        return [self._record_from_row(row) for row in rows]

    async def search_by_keyword(self, request: SearchRequest) -> SearchResult:
        await self.initialize()
        return await asyncio.to_thread(self._search_sync, request)

    def _search_sync(self, request: SearchRequest) -> SearchResult:
        expression = self._fts_expression(request.query)
        if not expression:
            return SearchResult(
                items=[],
                total=0,
                diagnostics={"strategy": "fts5", "reason": "query_has_no_tokens"},
            )

        clauses, parameters = self._filters(
            kinds=request.kinds, scopes=request.scopes, table_alias="m."
        )
        clauses.insert(0, "memories_fts MATCH ?")
        parameters.insert(0, expression)
        where = " AND ".join(clauses)

        count_sql = (
            "SELECT COUNT(*) AS count FROM memories_fts "
            "JOIN memories AS m ON m.id = memories_fts.id "
            f"WHERE {where}"
        )
        search_sql = (
            "SELECT m.record_json, bm25(memories_fts) AS rank FROM memories_fts "
            "JOIN memories AS m ON m.id = memories_fts.id "
            f"WHERE {where} ORDER BY rank ASC, m.created_at DESC "
            "LIMIT ? OFFSET ?"
        )
        with self._connect() as connection:
            total = int(connection.execute(count_sql, parameters).fetchone()["count"])
            rows = connection.execute(
                search_sql, [*parameters, request.limit, request.offset]
            ).fetchall()

        items = [
            SearchHit(
                record=self._record_from_row(row),
                score=1.0 / (1.0 + abs(float(row["rank"]))),
            )
            for row in rows
        ]
        return SearchResult(
            items=items,
            total=total,
            diagnostics={"strategy": "fts5", "query_tokens": len(expression.split(" AND "))},
        )

    @staticmethod
    def _filters(
        *,
        kinds: Sequence[MemoryKind] | None,
        scopes: Sequence[Scope] | None,
        table_alias: str,
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if kinds:
            placeholders = ", ".join("?" for _ in kinds)
            clauses.append(f"{table_alias}kind IN ({placeholders})")
            parameters.extend(kind.value for kind in kinds)
        if scopes:
            placeholders = ", ".join("?" for _ in scopes)
            clauses.append(f"{table_alias}scope IN ({placeholders})")
            parameters.extend(scope.value for scope in scopes)
        return clauses, parameters

    @staticmethod
    def _fts_expression(query: str) -> str:
        tokens = re.findall(r"\w+", query, flags=re.UNICODE)
        return " AND ".join(f'"{token}"' for token in tokens)

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord.model_validate_json(row["record_json"])


__all__ = ["LATEST_SCHEMA_VERSION", "SQLiteMemoryRepository"]
