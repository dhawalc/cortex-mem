"""SQLite/WAL repository for canonical AOMS records and semantic vectors.

The implementation uses the standard-library ``sqlite3`` driver and runs each
short database operation with ``asyncio.to_thread``. This keeps the public API
async-friendly without introducing an additional runtime dependency, while a
fresh connection per operation avoids sharing SQLite connections across worker
threads. WAL mode and a busy timeout allow concurrent readers and serialized
writes.

Vectors use ``sqlite-vec`` rather than a separate Chroma directory. sqlite-vec
is pre-1.0 but has a small, dependency-free native extension, exact cosine KNN,
and keeps records, the durable embedding queue, and vectors in one WAL-backed
database. This is operationally safer for the local-first product than two
stores with independent backup and consistency boundaries. Tables are created
per dimension because vec0 dimensions are fixed; provider/model partition keys
prevent accidentally comparing mathematically incompatible embeddings.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from aoms.contracts import (
    IntegrityReport,
    MemoryKind,
    MemoryRecord,
    RecallRequest,
    ReceiptPruneReport,
    Scope,
    ScopeContext,
    SearchHit,
    SearchRequest,
    SearchResult,
)
from aoms.embeddings import EmbeddingProfile, EmbeddingVector
from aoms.ownership import LEGACY_IMPORT_ACTOR, UNSCOPED_SQL, OwnershipSnapshot
from aoms.receipts import RecallReceipt
from aoms.repositories.base import (
    CompletedEmbedding,
    PendingEmbedding,
    RecallCandidate,
    RecallCandidateBatch,
    VectorHit,
)

LATEST_SCHEMA_VERSION = 6

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
    3: """
        CREATE TABLE IF NOT EXISTS vector_profiles (
            profile_key TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            dimensions INTEGER NOT NULL CHECK(dimensions > 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS embedding_pending (
            profile_key TEXT NOT NULL,
            record_id TEXT NOT NULL,
            record_updated_at TEXT NOT NULL,
            enqueued_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            claim_token TEXT,
            claimed_at TEXT,
            PRIMARY KEY(profile_key, record_id),
            FOREIGN KEY(profile_key) REFERENCES vector_profiles(profile_key),
            FOREIGN KEY(record_id) REFERENCES memories(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_embedding_pending_claim
            ON embedding_pending(profile_key, claimed_at, enqueued_at, record_id);
    """,
    4: """
        ALTER TABLE memories ADD COLUMN scope_agent_id TEXT;
        ALTER TABLE memories ADD COLUMN scope_workspace_id TEXT;
        ALTER TABLE memories ADD COLUMN created_by_agent_id TEXT;
        CREATE INDEX IF NOT EXISTS idx_memories_agent_scope
            ON memories(scope, scope_agent_id);
        CREATE INDEX IF NOT EXISTS idx_memories_workspace_scope
            ON memories(scope, scope_workspace_id);
        CREATE INDEX IF NOT EXISTS idx_memories_creator
            ON memories(created_by_agent_id);

        ALTER TABLE recall_receipts ADD COLUMN agent_id TEXT;
        ALTER TABLE recall_receipts ADD COLUMN workspace_id TEXT;
        CREATE INDEX IF NOT EXISTS idx_recall_receipts_agent_created
            ON recall_receipts(agent_id, created_at DESC, receipt_id DESC);
    """,
    5: """
        CREATE TABLE IF NOT EXISTS auth_tokens (
            token_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            scopes_json TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            salt BLOB NOT NULL,
            secret_hash BLOB NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            expires_at TEXT,
            revoked_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_auth_tokens_name
            ON auth_tokens(name);
        CREATE INDEX IF NOT EXISTS idx_auth_tokens_active
            ON auth_tokens(revoked_at, expires_at);
    """,
    # Migration 6 is implemented by ``_migrate_fts_rowids`` because the
    # rebuild must preserve the legacy FTS payload while changing its rowids.
    6: "",
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
        self._sqlite_vec_available: bool | None = None

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
        self._load_sqlite_vec(connection)
        if self.read_only:
            connection.execute("PRAGMA query_only = ON")
        else:
            connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _load_sqlite_vec(self, connection: sqlite3.Connection) -> None:
        """Load the packaged extension without making core SQLite unavailable."""

        try:
            import sqlite_vec

            connection.enable_load_extension(True)
            sqlite_vec.load(connection)
            connection.enable_load_extension(False)
            self._sqlite_vec_available = True
        except (ImportError, sqlite3.Error):
            try:
                connection.enable_load_extension(False)
            except (AttributeError, sqlite3.Error):
                pass
            self._sqlite_vec_available = False

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
                for row in connection.execute(
                    "SELECT version FROM schema_version"
                ).fetchall()
            }
            for version in sorted(MIGRATIONS):
                if version in applied:
                    continue
                if version == 6:
                    self._migrate_fts_rowids(connection)
                else:
                    connection.executescript(MIGRATIONS[version])
                    connection.execute(
                        "INSERT OR IGNORE INTO schema_version(version, applied_at) "
                        "VALUES (?, ?)",
                        (version, datetime.now(timezone.utc).isoformat()),
                    )
            connection.commit()

    @staticmethod
    def _migrate_fts_rowids(connection: sqlite3.Connection) -> None:
        """Atomically rebuild FTS so every entry uses its memory's rowid.

        The temporary source preserves the exact text indexed by older
        versions, including the normalization of structured content. Building
        it before the write transaction leaves the existing FTS table usable
        until the short atomic swap. If the process is interrupted, SQLite
        rolls the rebuild back and initialization can safely retry it.
        """

        connection.execute("DROP TABLE IF EXISTS temp.memories_fts_v6_source")
        connection.execute(
            """
            CREATE TEMP TABLE memories_fts_v6_source (
                rowid INTEGER PRIMARY KEY,
                id TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL,
                kind TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO memories_fts_v6_source(
                rowid, id, content, tags, kind
            )
            SELECT m.rowid, f.id, f.content, f.tags, f.kind
            FROM memories_fts AS f
            JOIN memories AS m ON m.id = f.id
            """
        )
        # A damaged legacy index may be missing a canonical row. Repair it
        # while rebuilding, without carrying forward orphan FTS entries.
        connection.execute(
            """
            INSERT INTO memories_fts_v6_source(rowid, id, content, tags, kind)
            SELECT
                m.rowid,
                m.id,
                json_extract(m.record_json, '$.content'),
                COALESCE((
                    SELECT group_concat(value, ' ')
                    FROM json_each(m.record_json, '$.tags')
                ), ''),
                m.kind
            FROM memories AS m
            LEFT JOIN memories_fts_v6_source AS f ON f.rowid = m.rowid
            WHERE f.rowid IS NULL
            """
        )
        connection.commit()

        memory_count = int(
            connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        )
        staged_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM memories_fts_v6_source"
            ).fetchone()[0]
        )
        misaligned_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM memories_fts_v6_source AS f
                JOIN memories AS m ON m.rowid = f.rowid
                WHERE m.id <> f.id
                """
            ).fetchone()[0]
        )
        if staged_count != memory_count or misaligned_count:
            raise RuntimeError(
                "could not build a complete rowid-aligned FTS migration source"
            )

        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("DROP TABLE memories_fts")
            connection.execute(
                """
                CREATE VIRTUAL TABLE memories_fts USING fts5(
                    id UNINDEXED,
                    content,
                    tags,
                    kind,
                    tokenize = 'unicode61'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO memories_fts(rowid, id, content, tags, kind)
                SELECT rowid, id, content, tags, kind
                FROM memories_fts_v6_source
                ORDER BY rowid
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_version(version, applied_at) "
                "VALUES (?, ?)",
                (6, datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

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

    async def store_new(self, record: MemoryRecord) -> MemoryRecord:
        """Insert exactly once; an existing id is never updated."""

        self._require_writable()
        await self.initialize()
        await asyncio.to_thread(self._store_many_sync, [record], None, True)
        return record

    async def store_with_embedding_pending(
        self, record: MemoryRecord, profile: EmbeddingProfile
    ) -> MemoryRecord:
        """Commit the canonical write and its durable embedding work atomically."""

        self._require_writable()
        await self.initialize()
        await asyncio.to_thread(self._store_many_sync, [record], profile)
        return record

    async def store_new_with_embedding_pending(
        self, record: MemoryRecord, profile: EmbeddingProfile
    ) -> MemoryRecord:
        """Atomically insert a new record and its embedding work, never upsert."""

        self._require_writable()
        await self.initialize()
        await asyncio.to_thread(self._store_many_sync, [record], profile, True)
        return record

    async def store_many(self, records: Sequence[MemoryRecord]) -> list[MemoryRecord]:
        self._require_writable()
        materialized = list(records)
        if not materialized:
            return []
        await self.initialize()
        await asyncio.to_thread(self._store_many_sync, materialized)
        return materialized

    async def store_many_new(
        self, records: Sequence[MemoryRecord]
    ) -> list[MemoryRecord]:
        """Insert a batch exactly once without scanning FTS for old rows."""

        self._require_writable()
        materialized = list(records)
        if not materialized:
            return []
        await self.initialize()
        await asyncio.to_thread(self._store_many_sync, materialized, None, True)
        return materialized

    def _store_many_sync(
        self,
        records: Sequence[MemoryRecord],
        embedding_profile: EmbeddingProfile | None = None,
        insert_only: bool = False,
    ) -> None:
        with self._connect() as connection:
            if embedding_profile is not None:
                self._register_profile(connection, embedding_profile)
            for record in records:
                serialized = record.model_dump_json()
                content_text = (
                    record.content
                    if isinstance(record.content, str)
                    else json.dumps(record.content, ensure_ascii=False, sort_keys=True)
                )
                insert_sql = """
                    INSERT INTO memories(
                        id, kind, scope, scope_agent_id, scope_workspace_id,
                        created_by_agent_id, created_at, updated_at, record_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                if not insert_only:
                    insert_sql += """
                    ON CONFLICT(id) DO UPDATE SET
                        kind = excluded.kind,
                        scope = excluded.scope,
                        scope_agent_id = excluded.scope_agent_id,
                        scope_workspace_id = excluded.scope_workspace_id,
                        created_by_agent_id = excluded.created_by_agent_id,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        record_json = excluded.record_json
                    """
                existing = connection.execute(
                    "SELECT rowid FROM memories WHERE id = ?", (record.id,)
                ).fetchone()
                if existing is not None and not insert_only:
                    connection.execute(
                        "DELETE FROM memories_fts WHERE rowid = ?",
                        (existing["rowid"],),
                    )
                connection.execute(
                    insert_sql,
                    (
                        record.id,
                        record.kind.value,
                        record.scope.value,
                        record.scope_agent_id,
                        record.scope_workspace_id,
                        record.created_by_agent_id,
                        record.created_at.isoformat(),
                        record.updated_at.isoformat(),
                        serialized,
                    ),
                )
                memory_rowid = connection.execute(
                    "SELECT rowid FROM memories WHERE id = ?", (record.id,)
                ).fetchone()["rowid"]
                connection.execute(
                    "INSERT INTO memories_fts(rowid, id, content, tags, kind) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        memory_rowid,
                        record.id,
                        content_text,
                        " ".join(record.tags),
                        record.kind.value,
                    ),
                )
                if embedding_profile is not None:
                    self._enqueue_record(connection, record, embedding_profile)
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

    async def visible_memory_count(
        self,
        *,
        kinds: Sequence[MemoryKind] | None = None,
        scopes: Sequence[Scope] | None = None,
        scope_context: ScopeContext | None = None,
    ) -> int:
        """Count records visible to a bound identity without reading content."""

        await self.initialize()
        return await asyncio.to_thread(
            self._visible_memory_count_sync, kinds, scopes, scope_context
        )

    def _visible_memory_count_sync(
        self,
        kinds: Sequence[MemoryKind] | None,
        scopes: Sequence[Scope] | None,
        scope_context: ScopeContext | None,
    ) -> int:
        clauses, parameters = self._filters(
            kinds=kinds,
            scopes=scopes,
            table_alias="",
            scope_context=scope_context,
        )
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM memories{where}", parameters
            ).fetchone()
        return int(row["count"])

    async def list(
        self,
        *,
        kinds: list[MemoryKind] | None = None,
        scopes: list[Scope] | None = None,
        limit: int = 100,
        offset: int = 0,
        scope_context: ScopeContext | None = None,
    ) -> list[MemoryRecord]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if offset < 0:
            raise ValueError("offset must not be negative")
        await self.initialize()
        return await asyncio.to_thread(
            self._list_sync, kinds, scopes, limit, offset, scope_context
        )

    def _list_sync(
        self,
        kinds: list[MemoryKind] | None,
        scopes: list[Scope] | None,
        limit: int,
        offset: int,
        scope_context: ScopeContext | None,
    ) -> list[MemoryRecord]:
        clauses, parameters = self._filters(
            kinds=kinds,
            scopes=scopes,
            table_alias="",
            scope_context=scope_context,
        )
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT record_json FROM memories"
            f"{where} ORDER BY created_at DESC, id ASC LIMIT ? OFFSET ?"
        )
        with self._connect() as connection:
            rows = connection.execute(sql, [*parameters, limit, offset]).fetchall()
        return [self._record_from_row(row) for row in rows]

    async def lineage(
        self,
        record_id: str,
        *,
        scope_context: ScopeContext,
        as_of: datetime | None = None,
    ) -> list[MemoryRecord]:
        """Return only scope-visible members connected by declared links."""

        await self.initialize()
        return await asyncio.to_thread(
            self._lineage_sync, record_id, scope_context, as_of
        )

    def _lineage_sync(
        self,
        record_id: str,
        scope_context: ScopeContext,
        as_of: datetime | None,
    ) -> list[MemoryRecord]:
        access, access_parameters = self._scope_access_filter(
            scope_context, table_alias="m."
        )
        recursive_access, recursive_parameters = self._scope_access_filter(
            scope_context, table_alias="linked."
        )
        boundary = " AND m.created_at <= ?" if as_of is not None else ""
        recursive_boundary = (
            " AND linked.created_at <= ?" if as_of is not None else ""
        )
        parameters: list[Any] = [record_id, *access_parameters]
        if as_of is not None:
            parameters.append(as_of.isoformat())
        parameters.extend(recursive_parameters)
        if as_of is not None:
            parameters.append(as_of.isoformat())
        sql = f"""
            WITH RECURSIVE chain(id, path, depth) AS (
                SELECT m.id, ',' || m.id || ',', 0
                FROM memories AS m
                WHERE m.id = ? AND {' AND '.join(access)}{boundary}
                UNION ALL
                SELECT linked.id, chain.path || linked.id || ',', chain.depth + 1
                FROM chain
                JOIN memories AS current ON current.id = chain.id
                JOIN memories AS linked ON (
                    linked.id = json_extract(current.record_json, '$.supersedes')
                    OR json_extract(linked.record_json, '$.supersedes') = current.id
                )
                WHERE chain.depth < 100
                  AND instr(chain.path, ',' || linked.id || ',') = 0
                  AND {' AND '.join(recursive_access)}{recursive_boundary}
            )
            SELECT DISTINCT m.record_json
            FROM chain JOIN memories AS m ON m.id = chain.id
            ORDER BY m.created_at ASC, m.id ASC
        """
        with self._connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._record_from_row(row) for row in rows]

    async def search_by_keyword(
        self,
        request: SearchRequest,
        *,
        scope_context: ScopeContext | None = None,
        as_of: datetime | None = None,
    ) -> SearchResult:
        await self.initialize()
        return await asyncio.to_thread(
            self._search_sync, request, scope_context, as_of
        )

    def _search_sync(
        self,
        request: SearchRequest,
        scope_context: ScopeContext | None,
        as_of: datetime | None,
    ) -> SearchResult:
        expression = self._fts_expression(request.query)
        if not expression:
            return SearchResult(
                items=[],
                total=0,
                diagnostics={"strategy": "fts5", "reason": "query_has_no_tokens"},
            )
        if as_of is not None:
            return self._search_as_of_sync(
                request, scope_context, as_of, expression
            )

        clauses, parameters = self._filters(
            kinds=request.kinds,
            scopes=request.scopes,
            table_alias="m.",
            scope_context=scope_context,
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
            scope_filtered_count = self._scope_filtered_fts_count(
                connection, expression, request, scope_context, as_of=as_of
            )
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
            diagnostics={
                "strategy": "fts5",
                "query_tokens": len(expression.split(" AND ")),
                "scope_filtered_count": scope_filtered_count,
                "as_of": as_of.isoformat() if as_of else None,
                "temporal_semantics": (
                    "declared-lineage reconstruction" if as_of else None
                ),
            },
        )

    def _search_as_of_sync(
        self,
        request: SearchRequest,
        scope_context: ScopeContext | None,
        as_of: datetime,
        expression: str,
    ) -> SearchResult:
        """Resolve FTS-matched declared chains at one authorized boundary.

        Matching any visible retained version discovers its visible lineage;
        the result is the version active at ``as_of``. This lets current topic
        wording find an older predecessor (and vice versa) without ever using
        an inaccessible record as an anchor or traversal step.
        """

        anchor_clauses, anchor_parameters = self._filters(
            kinds=request.kinds,
            scopes=request.scopes,
            table_alias="m.",
            scope_context=scope_context,
        )
        anchor_clauses.insert(0, "memories_fts MATCH ?")
        anchor_parameters.insert(0, expression)
        linked_access, linked_parameters = (
            self._scope_access_filter(scope_context, table_alias="linked.")
            if scope_context is not None
            else ([], [])
        )
        output_filters, output_parameters = self._filters(
            kinds=request.kinds,
            scopes=request.scopes,
            table_alias="m.",
            scope_context=scope_context,
        )
        successor_access, successor_parameters = (
            self._scope_access_filter(scope_context, table_alias="successor.")
            if scope_context is not None
            else ([], [])
        )
        linked_where = (
            " AND " + " AND ".join(linked_access) if linked_access else ""
        )
        output_where = (
            " AND " + " AND ".join(output_filters) if output_filters else ""
        )
        successor_where = (
            " AND " + " AND ".join(successor_access)
            if successor_access
            else ""
        )
        sql = f"""
            WITH RECURSIVE
            matched(id, rank) AS (
                SELECT m.id, bm25(memories_fts)
                FROM memories_fts
                JOIN memories AS m ON m.id = memories_fts.id
                WHERE {' AND '.join(anchor_clauses)}
            ),
            lineage(anchor_id, id, path, depth, rank) AS (
                SELECT id, id, ',' || id || ',', 0, rank FROM matched
                UNION ALL
                SELECT lineage.anchor_id, linked.id,
                       lineage.path || linked.id || ',', lineage.depth + 1,
                       lineage.rank
                FROM lineage
                JOIN memories AS current ON current.id = lineage.id
                JOIN memories AS linked ON (
                    linked.id = json_extract(current.record_json, '$.supersedes')
                    OR json_extract(linked.record_json, '$.supersedes') = current.id
                )
                WHERE lineage.depth < 100
                  AND instr(lineage.path, ',' || linked.id || ',') = 0
                  {linked_where}
            ),
            eligible AS (
                SELECT m.id, m.record_json, MIN(lineage.rank) AS rank
                FROM lineage JOIN memories AS m ON m.id = lineage.id
                WHERE m.created_at <= ?{output_where}
                  AND NOT EXISTS (
                      SELECT 1 FROM memories AS successor
                      WHERE json_extract(
                          successor.record_json, '$.supersedes'
                      ) = m.id
                        AND successor.created_at > m.created_at
                        AND successor.created_at <= ?{successor_where}
                  )
                GROUP BY m.id, m.record_json
            )
        """
        parameters = [
            *anchor_parameters,
            *linked_parameters,
            as_of.isoformat(),
            *output_parameters,
            as_of.isoformat(),
            *successor_parameters,
        ]
        with self._connect() as connection:
            total = int(
                connection.execute(
                    sql + "SELECT COUNT(*) AS count FROM eligible", parameters
                ).fetchone()["count"]
            )
            rows = connection.execute(
                sql
                + "SELECT record_json, rank FROM eligible "
                "ORDER BY rank ASC, json_extract(record_json, '$.created_at') DESC, "
                "id ASC LIMIT ? OFFSET ?",
                [*parameters, request.limit, request.offset],
            ).fetchall()
            scope_filtered_count = self._scope_filtered_fts_count(
                connection, expression, request, scope_context
            )
        return SearchResult(
            items=[
                SearchHit(
                    record=self._record_from_row(row),
                    score=1.0 / (1.0 + abs(float(row["rank"]))),
                )
                for row in rows
            ],
            total=total,
            diagnostics={
                "strategy": "fts5-declared-lineage",
                "query_tokens": len(expression.split(" AND ")),
                "scope_filtered_count": scope_filtered_count,
                "as_of": as_of.isoformat(),
                "temporal_semantics": "declared-lineage reconstruction",
            },
        )

    async def retrieve_recall_candidates(
        self,
        request: RecallRequest,
        *,
        limit: int = 100,
        query_vector: EmbeddingVector | None = None,
        vector_profile: EmbeddingProfile | None = None,
        scope_context: ScopeContext | None = None,
    ) -> RecallCandidateBatch:
        """Return the union of OR-FTS hits and newest records from each kind.

        Sampling two recent records per requested kind prevents a corpus's
        dominant kind from excluding every other kind before ranking. The
        engine performs the final deterministic ordering.
        """

        if limit < 1:
            raise ValueError("limit must be at least 1")
        await self.initialize()
        return await asyncio.to_thread(
            self._retrieve_recall_candidates_sync,
            request,
            limit,
            query_vector,
            vector_profile,
            scope_context,
        )

    def _retrieve_recall_candidates_sync(
        self,
        request: RecallRequest,
        limit: int,
        query_vector: EmbeddingVector | None,
        vector_profile: EmbeddingProfile | None,
        scope_context: ScopeContext | None,
    ) -> RecallCandidateBatch:
        expression = self._recall_fts_expression(request.task)
        fts_rows: list[sqlite3.Row] = []
        scope_filtered_count = 0
        with self._connect() as connection:
            if expression:
                clauses, parameters = self._filters(
                    kinds=request.kinds,
                    scopes=request.scopes,
                    table_alias="m.",
                    scope_context=scope_context,
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
                scope_filtered_count = self._scope_filtered_fts_count(
                    connection, expression, request, scope_context
                )

            candidates: dict[str, dict[str, Any]] = {}
            strengths = [max(0.0, -float(row["rank"])) for row in fts_rows]
            strongest = max(strengths, default=0.0)
            for position, (row, strength) in enumerate(
                zip(fts_rows, strengths, strict=True)
            ):
                record = self._record_from_row(row)
                normalized = (
                    strength / strongest if strongest > 0.0 else 1.0 / (position + 1)
                )
                candidates[record.id] = {
                    "record": record,
                    "fts_score": normalized,
                    "vector_score": None,
                    "sources": {"fts"},
                }

            if query_vector is not None and vector_profile is not None:
                vector_hits = self._vector_knn_with_connection(
                    connection,
                    query_vector,
                    vector_profile,
                    limit=limit,
                    kinds=request.kinds,
                    scopes=request.scopes,
                    scope_context=scope_context,
                )
                for hit in vector_hits:
                    row = connection.execute(
                        "SELECT record_json FROM memories WHERE id = ?",
                        (hit.memory_id,),
                    ).fetchone()
                    if row is None:
                        continue
                    record = self._record_from_row(row)
                    existing = candidates.setdefault(
                        record.id,
                        {
                            "record": record,
                            "fts_score": 0.0,
                            "vector_score": None,
                            "sources": set(),
                        },
                    )
                    existing["vector_score"] = hit.score
                    existing["sources"].add("vector")

            kinds = request.kinds or list(MemoryKind)
            for kind in kinds:
                clauses, parameters = self._filters(
                    kinds=[kind],
                    scopes=request.scopes,
                    table_alias="",
                    scope_context=scope_context,
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
                        {
                            "record": record,
                            "fts_score": 0.0,
                            "vector_score": None,
                            "sources": set(),
                        },
                    )
                    existing["sources"].add("recent-kind")

        return RecallCandidateBatch(
            candidates=tuple(
                RecallCandidate(
                    record=value["record"],
                    fts_score=float(value["fts_score"]),
                    retrieval_sources=tuple(sorted(value["sources"])),
                    vector_score=value["vector_score"],
                )
                for value in candidates.values()
            ),
            scope_filtered_count=scope_filtered_count,
        )

    async def upsert_vector(
        self,
        record: MemoryRecord,
        profile: EmbeddingProfile,
        vector: EmbeddingVector,
    ) -> None:
        self._require_writable()
        await self.initialize()
        await asyncio.to_thread(self._upsert_vector_sync, record, profile, vector)

    def _upsert_vector_sync(
        self,
        record: MemoryRecord,
        profile: EmbeddingProfile,
        vector: EmbeddingVector,
    ) -> None:
        with self._connect() as connection:
            self._register_profile(connection, profile)
            self._upsert_vector_with_connection(connection, record, profile, vector)
            connection.commit()

    async def vector_knn(
        self,
        vector: EmbeddingVector,
        profile: EmbeddingProfile,
        *,
        limit: int,
        kinds: Sequence[MemoryKind] | None = None,
        scopes: Sequence[Scope] | None = None,
        scope_context: ScopeContext | None = None,
    ) -> list[VectorHit]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        await self.initialize()
        return await asyncio.to_thread(
            self._vector_knn_sync,
            vector,
            profile,
            limit,
            kinds,
            scopes,
            scope_context,
        )

    def _vector_knn_sync(
        self,
        vector: EmbeddingVector,
        profile: EmbeddingProfile,
        limit: int,
        kinds: Sequence[MemoryKind] | None,
        scopes: Sequence[Scope] | None,
        scope_context: ScopeContext | None,
    ) -> list[VectorHit]:
        with self._connect() as connection:
            return self._vector_knn_with_connection(
                connection,
                vector,
                profile,
                limit=limit,
                kinds=kinds,
                scopes=scopes,
                scope_context=scope_context,
            )

    def _vector_knn_with_connection(
        self,
        connection: sqlite3.Connection,
        vector: EmbeddingVector,
        profile: EmbeddingProfile,
        *,
        limit: int,
        kinds: Sequence[MemoryKind] | None,
        scopes: Sequence[Scope] | None,
        scope_context: ScopeContext | None = None,
    ) -> list[VectorHit]:
        self._validate_vector(profile, vector)
        if not self._sqlite_vec_available:
            return []
        table = self._vector_table(profile.dimensions)
        if not self._table_exists(connection, table):
            return []
        requested_kinds = list(kinds) if kinds else list(MemoryKind)
        requested_scopes = list(scopes) if scopes else list(Scope)
        serialized = json.dumps(vector, separators=(",", ":"))
        best: dict[str, float] = {}
        for kind in requested_kinds:
            for scope in requested_scopes:
                namespace = self._vector_namespace(kind, scope)
                rows = connection.execute(
                    f"SELECT memory_id, distance FROM {table} "
                    "WHERE embedding MATCH ? AND k = ? "
                    "AND profile_key = ? AND namespace = ? "
                    "ORDER BY distance",
                    (serialized, limit, profile.key, namespace),
                ).fetchall()
                for row in rows:
                    if scope_context is not None:
                        access_clauses, access_parameters = self._scope_access_filter(
                            scope_context, table_alias=""
                        )
                        visible = connection.execute(
                            "SELECT 1 FROM memories WHERE id = ? AND "
                            + " AND ".join(access_clauses),
                            (row["memory_id"], *access_parameters),
                        ).fetchone()
                        if visible is None:
                            continue
                    score = min(1.0, max(0.0, 1.0 - float(row["distance"])))
                    best[row["memory_id"]] = max(best.get(row["memory_id"], 0.0), score)
        ordered = sorted(best.items(), key=lambda item: (-item[1], item[0]))
        return [
            VectorHit(memory_id=memory_id, score=score)
            for memory_id, score in ordered[:limit]
        ]

    async def claim_pending_embeddings(
        self,
        profile: EmbeddingProfile,
        *,
        limit: int,
        lease_seconds: int = 300,
    ) -> list[PendingEmbedding]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        self._require_writable()
        await self.initialize()
        return await asyncio.to_thread(
            self._claim_pending_embeddings_sync, profile, limit, lease_seconds
        )

    def _claim_pending_embeddings_sync(
        self, profile: EmbeddingProfile, limit: int, lease_seconds: int
    ) -> list[PendingEmbedding]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=lease_seconds)
        claim_token = str(uuid4())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT p.record_id, p.attempts, m.record_json "
                "FROM embedding_pending AS p "
                "JOIN memories AS m ON m.id = p.record_id "
                "WHERE p.profile_key = ? "
                "AND (p.claimed_at IS NULL OR p.claimed_at < ?) "
                "ORDER BY p.enqueued_at, p.record_id LIMIT ?",
                (profile.key, cutoff.isoformat(), limit),
            ).fetchall()
            record_ids = [row["record_id"] for row in rows]
            if record_ids:
                placeholders = ", ".join("?" for _ in record_ids)
                connection.execute(
                    f"UPDATE embedding_pending SET claim_token = ?, claimed_at = ? "
                    f"WHERE profile_key = ? AND record_id IN ({placeholders})",
                    (claim_token, now.isoformat(), profile.key, *record_ids),
                )
            connection.commit()
        return [
            PendingEmbedding(
                record=self._record_from_row(row),
                profile=profile,
                claim_token=claim_token,
                attempts=int(row["attempts"]),
            )
            for row in rows
        ]

    async def complete_pending_embeddings(
        self, completed: Sequence[CompletedEmbedding]
    ) -> int:
        materialized = list(completed)
        if not materialized:
            return 0
        self._require_writable()
        await self.initialize()
        return await asyncio.to_thread(
            self._complete_pending_embeddings_sync, materialized
        )

    def _complete_pending_embeddings_sync(
        self, completed: Sequence[CompletedEmbedding]
    ) -> int:
        count = 0
        with self._connect() as connection:
            for item in completed:
                pending = item.pending
                row = connection.execute(
                    "SELECT updated_at FROM memories WHERE id = ?",
                    (pending.record.id,),
                ).fetchone()
                if (
                    row is None
                    or row["updated_at"] != pending.record.updated_at.isoformat()
                ):
                    continue
                self._register_profile(connection, pending.profile)
                self._upsert_vector_with_connection(
                    connection, pending.record, pending.profile, item.vector
                )
                cursor = connection.execute(
                    "DELETE FROM embedding_pending WHERE profile_key = ? "
                    "AND record_id = ? AND record_updated_at = ? AND claim_token = ?",
                    (
                        pending.profile.key,
                        pending.record.id,
                        pending.record.updated_at.isoformat(),
                        pending.claim_token,
                    ),
                )
                count += cursor.rowcount
            connection.commit()
        return count

    async def fail_pending_embeddings(
        self, pending: Sequence[PendingEmbedding], error: str
    ) -> int:
        materialized = list(pending)
        if not materialized:
            return 0
        self._require_writable()
        await self.initialize()
        return await asyncio.to_thread(
            self._fail_pending_embeddings_sync, materialized, error[:2_000]
        )

    def _fail_pending_embeddings_sync(
        self, pending: Sequence[PendingEmbedding], error: str
    ) -> int:
        count = 0
        with self._connect() as connection:
            for item in pending:
                cursor = connection.execute(
                    "UPDATE embedding_pending SET attempts = attempts + 1, "
                    "last_error = ?, claim_token = NULL, claimed_at = NULL "
                    "WHERE profile_key = ? AND record_id = ? AND claim_token = ?",
                    (error, item.profile.key, item.record.id, item.claim_token),
                )
                count += cursor.rowcount
            connection.commit()
        return count

    async def scan_records_for_embedding(
        self,
        profile: EmbeddingProfile,
        *,
        after_id: str | None,
        limit: int,
    ) -> tuple[list[MemoryRecord], str | None, int]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        await self.initialize()
        return await asyncio.to_thread(
            self._scan_records_for_embedding_sync, profile, after_id, limit
        )

    def _scan_records_for_embedding_sync(
        self, profile: EmbeddingProfile, after_id: str | None, limit: int
    ) -> tuple[list[MemoryRecord], str | None, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, updated_at, record_json FROM memories "
                "WHERE (? IS NULL OR id > ?) ORDER BY id LIMIT ?",
                (after_id, after_id, limit),
            ).fetchall()
            if not rows:
                return [], None, 0
            table = self._vector_table(profile.dimensions)
            table_exists = self._sqlite_vec_available and self._table_exists(
                connection, table
            )
            records: list[MemoryRecord] = []
            for row in rows:
                current = None
                if table_exists:
                    current = connection.execute(
                        f"SELECT record_updated_at FROM {table} WHERE vector_id = ?",
                        (self._vector_id(profile, row["id"]),),
                    ).fetchone()
                if current is None or current["record_updated_at"] != row["updated_at"]:
                    records.append(self._record_from_row(row))
            return records, rows[-1]["id"], len(rows)

    async def enqueue_unembedded(
        self, records: Sequence[MemoryRecord], profile: EmbeddingProfile
    ) -> int:
        materialized = list(records)
        if not materialized:
            return 0
        self._require_writable()
        await self.initialize()
        return await asyncio.to_thread(
            self._enqueue_unembedded_sync, materialized, profile
        )

    def _enqueue_unembedded_sync(
        self, records: Sequence[MemoryRecord], profile: EmbeddingProfile
    ) -> int:
        count = 0
        with self._connect() as connection:
            self._register_profile(connection, profile)
            for record in records:
                count += self._enqueue_record(connection, record, profile)
            connection.commit()
        return count

    async def pending_embedding_count(self, profile: EmbeddingProfile) -> int:
        await self.initialize()
        return await asyncio.to_thread(self._pending_embedding_count_sync, profile)

    def _pending_embedding_count_sync(self, profile: EmbeddingProfile) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM embedding_pending WHERE profile_key = ?",
                (profile.key,),
            ).fetchone()
        return int(row["count"])

    async def save_recall_receipt(self, receipt: RecallReceipt) -> None:
        self._require_writable()
        await self.initialize()
        await asyncio.to_thread(self._save_recall_receipt_sync, receipt)

    def _save_recall_receipt_sync(self, receipt: RecallReceipt) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO recall_receipts(
                    receipt_id, created_at, agent_id, workspace_id, receipt_json
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(receipt_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    agent_id = excluded.agent_id,
                    workspace_id = excluded.workspace_id,
                    receipt_json = excluded.receipt_json
                """,
                (
                    receipt.receipt_id,
                    receipt.created_at.isoformat(),
                    receipt.agent_id,
                    receipt.workspace_id,
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

    async def recent_recall_receipts(
        self, *, limit: int = 20, scope_context: ScopeContext | None = None
    ) -> list[RecallReceipt]:
        if limit < 1 or limit > 1_000:
            raise ValueError("limit must be between 1 and 1000")
        await self.initialize()
        return await asyncio.to_thread(
            self._recent_recall_receipts_sync, limit, scope_context
        )

    def _recent_recall_receipts_sync(
        self, limit: int, scope_context: ScopeContext | None
    ) -> list[RecallReceipt]:
        with self._connect() as connection:
            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'recall_receipts'"
            ).fetchone()
            if table_exists is None:
                return []
            if scope_context is None:
                rows = connection.execute(
                    "SELECT receipt_json FROM recall_receipts "
                    "ORDER BY created_at DESC, receipt_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT receipt_json FROM recall_receipts WHERE agent_id = ? "
                    "ORDER BY created_at DESC, receipt_id DESC LIMIT ?",
                    (scope_context.agent_id, limit),
                ).fetchall()
        return [RecallReceipt.model_validate_json(row["receipt_json"]) for row in rows]

    async def prune_recall_receipts(
        self, *, retain: int | None = None
    ) -> ReceiptPruneReport:
        self._require_writable()
        keep = self.receipt_retention if retain is None else retain
        if keep < 0:
            raise ValueError("retain must not be negative")
        await self.initialize()
        return await asyncio.to_thread(self._prune_recall_receipts_sync, keep)

    def _prune_recall_receipts_sync(self, retain: int) -> ReceiptPruneReport:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM recall_receipts WHERE receipt_id NOT IN ("
                "SELECT receipt_id FROM recall_receipts "
                "ORDER BY created_at DESC, receipt_id DESC LIMIT ?)",
                (retain,),
            )
            connection.commit()
            remaining = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM recall_receipts"
                ).fetchone()["count"]
            )
            return ReceiptPruneReport(
                retained_limit=retain,
                deleted_count=cursor.rowcount,
                remaining_count=remaining,
            )

    async def integrity_report(self) -> IntegrityReport:
        await self.initialize()
        return await asyncio.to_thread(self._integrity_report_sync)

    async def ownership_snapshot(self) -> OwnershipSnapshot:
        """Count only records that the scope integrity rule considers unscoped."""

        await self.initialize()
        return await asyncio.to_thread(self._ownership_snapshot_sync)

    def _ownership_snapshot_sync(self) -> OwnershipSnapshot:
        with self._connect() as connection:
            unscoped_records = int(
                connection.execute(
                    f"SELECT COUNT(*) AS count FROM memories WHERE {UNSCOPED_SQL}"
                ).fetchone()["count"]
            )
            by_kind = {
                str(row["bucket"]): int(row["count"])
                for row in connection.execute(
                    "SELECT kind AS bucket, COUNT(*) AS count FROM memories "
                    f"WHERE {UNSCOPED_SQL} GROUP BY kind ORDER BY kind"
                ).fetchall()
            }
            by_tier = {
                str(row["bucket"]): int(row["count"])
                for row in connection.execute(
                    "SELECT COALESCE(NULLIF(json_extract(record_json, "
                    "'$.provenance.tier'), ''), 'unknown') AS bucket, "
                    "COUNT(*) AS count FROM memories "
                    f"WHERE {UNSCOPED_SQL} GROUP BY bucket ORDER BY bucket"
                ).fetchall()
            }
        return OwnershipSnapshot(
            unscoped_records=unscoped_records,
            by_kind=by_kind,
            by_tier=by_tier,
        )

    async def assign_unscoped_user_global_batch(
        self,
        *,
        limit: int,
        assignment_timestamp: str,
        tool_version: str,
        reason: str,
    ) -> int:
        """Assign one atomic batch; reruns cannot select completed records."""

        if limit < 1:
            raise ValueError("limit must be at least 1")
        self._require_writable()
        await self.initialize()
        return await asyncio.to_thread(
            self._assign_unscoped_user_global_batch_sync,
            limit,
            assignment_timestamp,
            tool_version,
            reason,
        )

    def _assign_unscoped_user_global_batch_sync(
        self,
        limit: int,
        assignment_timestamp: str,
        tool_version: str,
        reason: str,
    ) -> int:
        annotation = {
            "assignment_timestamp": assignment_timestamp,
            "tool_version": tool_version,
            "reason": reason,
        }
        assigned = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, record_json FROM memories "
                f"WHERE {UNSCOPED_SQL} ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            for row in rows:
                record = self._record_from_row(row)
                provenance = record.provenance.model_copy(
                    update={
                        "details": {
                            **record.provenance.details,
                            "ownership_assignment": annotation,
                        }
                    }
                )
                assigned_record = record.model_copy(
                    update={
                        "scope": Scope.USER_GLOBAL,
                        "scope_agent_id": None,
                        "scope_workspace_id": None,
                        "created_by_agent_id": (
                            record.created_by_agent_id or LEGACY_IMPORT_ACTOR
                        ),
                        "provenance": provenance,
                    }
                )
                cursor = connection.execute(
                    "UPDATE memories SET scope = ?, scope_agent_id = NULL, "
                    "scope_workspace_id = NULL, created_by_agent_id = ?, "
                    "record_json = ? WHERE id = ? AND (" + UNSCOPED_SQL + ")",
                    (
                        Scope.USER_GLOBAL.value,
                        assigned_record.created_by_agent_id,
                        assigned_record.model_dump_json(),
                        assigned_record.id,
                    ),
                )
                assigned += cursor.rowcount
            connection.commit()
        return assigned

    def _integrity_report_sync(self) -> IntegrityReport:
        with self._connect() as connection:
            memory_count = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM memories"
                ).fetchone()["count"]
            )
            fts_count = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM memories_fts"
                ).fetchone()["count"]
            )
            missing_fts = [
                row["id"]
                for row in connection.execute(
                    "SELECT m.id FROM memories AS m "
                    "LEFT JOIN memories_fts AS f ON f.id = m.id "
                    "WHERE f.id IS NULL ORDER BY m.id"
                ).fetchall()
            ]
            orphan_fts = [
                row["id"]
                for row in connection.execute(
                    "SELECT DISTINCT f.id FROM memories_fts AS f "
                    "LEFT JOIN memories AS m ON m.id = f.id "
                    "WHERE m.id IS NULL ORDER BY f.id"
                ).fetchall()
            ]
            unscoped = [
                row["id"]
                for row in connection.execute(
                    f"SELECT id FROM memories WHERE {UNSCOPED_SQL} ORDER BY id"
                ).fetchall()
            ]

            table_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name GLOB 'memory_vectors_[0-9]*' ORDER BY name"
            ).fetchall()
            vector_table_counts: dict[str, int] = {}
            orphan_vectors: set[str] = set()
            for row in table_rows:
                table = row["name"]
                if re.fullmatch(r"memory_vectors_\d+", table) is None:
                    continue
                vector_table_counts[table] = int(
                    connection.execute(
                        f"SELECT COUNT(*) AS count FROM {table}"
                    ).fetchone()["count"]
                )
                orphan_vectors.update(
                    item["memory_id"]
                    for item in connection.execute(
                        f"SELECT DISTINCT v.memory_id FROM {table} AS v "
                        "LEFT JOIN memories AS m ON m.id = v.memory_id "
                        "WHERE m.id IS NULL"
                    ).fetchall()
                )

        vector_count = sum(vector_table_counts.values())
        healthy = not (
            missing_fts or orphan_fts or orphan_vectors or unscoped
        ) and memory_count == fts_count
        return IntegrityReport(
            healthy=healthy,
            memory_count=memory_count,
            fts_count=fts_count,
            vector_count=vector_count,
            vector_table_counts=vector_table_counts,
            missing_fts_memory_ids=missing_fts,
            orphan_fts_memory_ids=orphan_fts,
            orphan_vector_memory_ids=sorted(orphan_vectors),
            unscoped_memory_ids=unscoped,
        )

    @staticmethod
    def _filters(
        *,
        kinds: Sequence[MemoryKind] | None,
        scopes: Sequence[Scope] | None,
        table_alias: str,
        scope_context: ScopeContext | None = None,
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
        if scope_context is not None:
            access_clauses, access_parameters = SQLiteMemoryRepository._scope_access_filter(
                scope_context, table_alias=table_alias
            )
            clauses.extend(access_clauses)
            parameters.extend(access_parameters)
        return clauses, parameters

    @staticmethod
    def _scope_access_filter(
        scope_context: ScopeContext, *, table_alias: str
    ) -> tuple[list[str], list[Any]]:
        return [
            "("
            f"{table_alias}scope = ? OR "
            f"({table_alias}scope = ? AND {table_alias}scope_workspace_id = ?) OR "
            f"({table_alias}scope = ? AND {table_alias}scope_agent_id = ?)"
            ")"
        ], [
            Scope.USER_GLOBAL.value,
            Scope.WORKSPACE.value,
            scope_context.workspace_id,
            Scope.AGENT_PRIVATE.value,
            scope_context.agent_id,
        ]

    def _scope_filtered_fts_count(
        self,
        connection: sqlite3.Connection,
        expression: str,
        request: SearchRequest | RecallRequest,
        scope_context: ScopeContext | None,
        as_of: datetime | None = None,
    ) -> int:
        if scope_context is None:
            return 0
        unscoped_clauses, unscoped_parameters = self._filters(
            kinds=request.kinds,
            scopes=request.scopes,
            table_alias="m.",
        )
        unscoped_clauses.insert(0, "memories_fts MATCH ?")
        unscoped_parameters.insert(0, expression)
        if as_of is not None:
            unscoped_clauses.append("m.created_at <= ?")
            unscoped_parameters.append(as_of.isoformat())
        unscoped = connection.execute(
            "SELECT COUNT(*) AS count FROM memories_fts "
            "JOIN memories AS m ON m.id = memories_fts.id "
            f"WHERE {' AND '.join(unscoped_clauses)}",
            unscoped_parameters,
        ).fetchone()["count"]
        scoped_clauses, scoped_parameters = self._filters(
            kinds=request.kinds,
            scopes=request.scopes,
            table_alias="m.",
            scope_context=scope_context,
        )
        scoped_clauses.insert(0, "memories_fts MATCH ?")
        scoped_parameters.insert(0, expression)
        if as_of is not None:
            scoped_clauses.append("m.created_at <= ?")
            scoped_parameters.append(as_of.isoformat())
        scoped = connection.execute(
            "SELECT COUNT(*) AS count FROM memories_fts "
            "JOIN memories AS m ON m.id = memories_fts.id "
            f"WHERE {' AND '.join(scoped_clauses)}",
            scoped_parameters,
        ).fetchone()["count"]
        return max(0, int(unscoped) - int(scoped))

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

    @staticmethod
    def _register_profile(
        connection: sqlite3.Connection, profile: EmbeddingProfile
    ) -> None:
        connection.execute(
            "INSERT INTO vector_profiles(profile_key, provider, model, dimensions, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(profile_key) DO NOTHING",
            (
                profile.key,
                profile.provider,
                profile.model,
                profile.dimensions,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    @staticmethod
    def _vector_table(dimensions: int) -> str:
        if dimensions < 1 or dimensions > 65_536:
            raise ValueError("embedding dimensions must be between 1 and 65536")
        return f"memory_vectors_{dimensions}"

    @staticmethod
    def _vector_id(profile: EmbeddingProfile, record_id: str) -> str:
        return hashlib.sha256(f"{profile.key}\0{record_id}".encode()).hexdigest()

    @staticmethod
    def _vector_namespace(kind: MemoryKind, scope: Scope) -> str:
        return f"{kind.value}|{scope.value}"

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )

    def _ensure_vector_table(
        self, connection: sqlite3.Connection, profile: EmbeddingProfile
    ) -> str:
        if not self._sqlite_vec_available:
            raise RuntimeError(
                "sqlite-vec is unavailable; install sqlite-vec to persist embeddings"
            )
        table = self._vector_table(profile.dimensions)
        connection.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
            "vector_id TEXT PRIMARY KEY, "
            f"embedding FLOAT[{profile.dimensions}] distance_metric=cosine, "
            "profile_key TEXT PARTITION KEY, "
            "namespace TEXT PARTITION KEY, "
            "+memory_id TEXT, "
            "+record_updated_at TEXT)"
        )
        return table

    @staticmethod
    def _validate_vector(profile: EmbeddingProfile, vector: Sequence[float]) -> None:
        if len(vector) != profile.dimensions:
            raise ValueError(
                f"vector has {len(vector)} dimensions; expected {profile.dimensions}"
            )
        if not all(math.isfinite(float(value)) for value in vector):
            raise ValueError("vector values must be finite")

    def _upsert_vector_with_connection(
        self,
        connection: sqlite3.Connection,
        record: MemoryRecord,
        profile: EmbeddingProfile,
        vector: EmbeddingVector,
    ) -> None:
        self._validate_vector(profile, vector)
        table = self._ensure_vector_table(connection, profile)
        vector_id = self._vector_id(profile, record.id)
        connection.execute(f"DELETE FROM {table} WHERE vector_id = ?", (vector_id,))
        connection.execute(
            f"INSERT INTO {table}("
            "vector_id, embedding, profile_key, namespace, memory_id, record_updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                vector_id,
                json.dumps(vector, separators=(",", ":")),
                profile.key,
                self._vector_namespace(record.kind, record.scope),
                record.id,
                record.updated_at.isoformat(),
            ),
        )

    def _enqueue_record(
        self,
        connection: sqlite3.Connection,
        record: MemoryRecord,
        profile: EmbeddingProfile,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        existing = connection.execute(
            "SELECT record_updated_at FROM embedding_pending "
            "WHERE profile_key = ? AND record_id = ?",
            (profile.key, record.id),
        ).fetchone()
        connection.execute(
            "INSERT INTO embedding_pending("
            "profile_key, record_id, record_updated_at, enqueued_at"
            ") VALUES (?, ?, ?, ?) "
            "ON CONFLICT(profile_key, record_id) DO UPDATE SET "
            "record_updated_at = excluded.record_updated_at, "
            "enqueued_at = excluded.enqueued_at, attempts = 0, last_error = NULL, "
            "claim_token = NULL, claimed_at = NULL "
            "WHERE embedding_pending.record_updated_at != excluded.record_updated_at",
            (profile.key, record.id, record.updated_at.isoformat(), now),
        )
        return int(
            existing is None
            or existing["record_updated_at"] != record.updated_at.isoformat()
        )

    def _require_writable(self) -> None:
        if self.read_only:
            raise RuntimeError("repository is read-only")

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord.model_validate_json(row["record_json"])


__all__ = ["LATEST_SCHEMA_VERSION", "SQLiteMemoryRepository"]
