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
    RecallRequest,
    Scope,
    SearchHit,
    SearchRequest,
    SearchResult,
)
from aoms.receipts import RecallReceipt
from aoms.repositories.base import RecallCandidate

LATEST_SCHEMA_VERSION = 2

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
    2: """
        CREATE TABLE IF NOT EXISTS recall_receipts (
            receipt_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            receipt_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recall_receipts_created_at
            ON recall_receipts(created_at DESC, receipt_id DESC);
    """,
}


class SQLiteMemoryRepository:
    """Store canonical records in a portable SQLite database with FTS5."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        read_only: bool = False,
        receipt_retention: int = 1_000,
    ):
        if receipt_retention < 1:
            raise ValueError("receipt_retention must be at least 1")
        self.db_path = Path(db_path)
        self.read_only = read_only
        self.receipt_retention = receipt_retention
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
        target = (
            f"{self.db_path.expanduser().resolve().as_uri()}?mode=ro"
            if self.read_only
            else str(self.db_path)
        )
        connection = sqlite3.connect(
            target,
            timeout=30.0,
            uri=self.read_only,
        )
        connection.row_factory = sqlite3.Row
        if self.read_only:
            connection.execute("PRAGMA query_only = ON")
        else:
            connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_sync(self) -> None:
        if self.read_only:
            with self._connect() as connection:
                available = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                    ).fetchall()
                }
            required = {"memories", "memories_fts"}
            if not required.issubset(available):
                missing = ", ".join(sorted(required - available))
                raise RuntimeError(f"read-only AOMS database is missing: {missing}")
            return
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
        self._require_writable()
        await self.initialize()
        await asyncio.to_thread(self._store_many_sync, [record])
        return record

    async def store_many(self, records: Sequence[MemoryRecord]) -> list[MemoryRecord]:
        self._require_writable()
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

    async def retrieve_recall_candidates(
        self, request: RecallRequest, *, limit: int = 100
    ) -> list[RecallCandidate]:
        """Return the union of OR-FTS hits and newest records from each kind.

        Sampling two recent records per requested kind prevents a corpus's
        dominant kind from excluding every other kind before ranking. The
        engine performs the final deterministic ordering.
        """

        if limit < 1:
            raise ValueError("limit must be at least 1")
        await self.initialize()
        return await asyncio.to_thread(self._retrieve_recall_candidates_sync, request, limit)

    def _retrieve_recall_candidates_sync(
        self, request: RecallRequest, limit: int
    ) -> list[RecallCandidate]:
        expression = self._recall_fts_expression(request.task)
        fts_rows: list[sqlite3.Row] = []
        with self._connect() as connection:
            if expression:
                clauses, parameters = self._filters(
                    kinds=request.kinds, scopes=request.scopes, table_alias="m."
                )
                clauses.insert(0, "memories_fts MATCH ?")
                parameters.insert(0, expression)
                fts_rows = connection.execute(
                    "SELECT m.record_json, bm25(memories_fts) AS rank "
                    "FROM memories_fts "
                    "JOIN memories AS m ON m.id = memories_fts.id "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY rank ASC, m.updated_at DESC, m.id ASC LIMIT ?",
                    [*parameters, limit],
                ).fetchall()

            candidates: dict[str, dict[str, Any]] = {}
            strengths = [max(0.0, -float(row["rank"])) for row in fts_rows]
            strongest = max(strengths, default=0.0)
            for position, (row, strength) in enumerate(zip(fts_rows, strengths, strict=True)):
                record = self._record_from_row(row)
                normalized = (
                    strength / strongest if strongest > 0.0 else 1.0 / (position + 1)
                )
                candidates[record.id] = {
                    "record": record,
                    "fts_score": normalized,
                    "sources": {"fts"},
                }

            kinds = request.kinds or list(MemoryKind)
            for kind in kinds:
                clauses, parameters = self._filters(
                    kinds=[kind], scopes=request.scopes, table_alias=""
                )
                recent_rows = connection.execute(
                    "SELECT record_json FROM memories "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY updated_at DESC, id ASC LIMIT 2",
                    parameters,
                ).fetchall()
                for row in recent_rows:
                    record = self._record_from_row(row)
                    existing = candidates.setdefault(
                        record.id,
                        {"record": record, "fts_score": 0.0, "sources": set()},
                    )
                    existing["sources"].add("recent-kind")

        return [
            RecallCandidate(
                record=value["record"],
                fts_score=float(value["fts_score"]),
                retrieval_sources=tuple(sorted(value["sources"])),
            )
            for value in candidates.values()
        ]

    async def save_recall_receipt(self, receipt: RecallReceipt) -> None:
        self._require_writable()
        await self.initialize()
        await asyncio.to_thread(self._save_recall_receipt_sync, receipt)

    def _save_recall_receipt_sync(self, receipt: RecallReceipt) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO recall_receipts(receipt_id, created_at, receipt_json)
                VALUES (?, ?, ?)
                ON CONFLICT(receipt_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    receipt_json = excluded.receipt_json
                """,
                (
                    receipt.receipt_id,
                    receipt.created_at.isoformat(),
                    receipt.model_dump_json(),
                ),
            )
            connection.execute(
                """
                DELETE FROM recall_receipts
                WHERE receipt_id NOT IN (
                    SELECT receipt_id FROM recall_receipts
                    ORDER BY created_at DESC, receipt_id DESC
                    LIMIT ?
                )
                """,
                (self.receipt_retention,),
            )
            connection.commit()

    async def recent_recall_receipts(self, *, limit: int = 20) -> list[RecallReceipt]:
        if limit < 1 or limit > 1_000:
            raise ValueError("limit must be between 1 and 1000")
        await self.initialize()
        return await asyncio.to_thread(self._recent_recall_receipts_sync, limit)

    def _recent_recall_receipts_sync(self, limit: int) -> list[RecallReceipt]:
        with self._connect() as connection:
            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'recall_receipts'"
            ).fetchone()
            if table_exists is None:
                return []
            rows = connection.execute(
                "SELECT receipt_json FROM recall_receipts "
                "ORDER BY created_at DESC, receipt_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [RecallReceipt.model_validate_json(row["receipt_json"]) for row in rows]

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
    def _recall_fts_expression(query: str) -> str:
        stopwords = {
            "a",
            "an",
            "and",
            "for",
            "happened",
            "in",
            "is",
            "of",
            "on",
            "the",
            "to",
            "was",
            "what",
            "with",
        }
        all_tokens = re.findall(r"\w+", query, flags=re.UNICODE)
        keywords = [token for token in all_tokens if token.casefold() not in stopwords]
        tokens: list[str] = []
        seen: set[str] = set()
        for token in keywords or all_tokens:
            folded = token.casefold()
            if folded not in seen:
                tokens.append(token)
                seen.add(folded)
            if len(tokens) == 32:
                break
        return " OR ".join(f'"{token}"' for token in tokens)

    def _require_writable(self) -> None:
        if self.read_only:
            raise RuntimeError("repository is read-only")

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord.model_validate_json(row["record_json"])


__all__ = ["LATEST_SCHEMA_VERSION", "SQLiteMemoryRepository"]
