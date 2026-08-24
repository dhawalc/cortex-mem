"""Bounded, read-only SQLite queries for the Recall Observatory.

This repository intentionally does not implement the writable AOMS repository
protocol. Every collection query applies its limit in SQLite and returns at
most one extra row to determine whether another page exists.
"""

from __future__ import annotations

import base64
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from aoms.contracts import ContestEntry, MemoryKind, MemoryRecord, Scope
from aoms.receipts import RecallReceipt
from aoms.repositories.sqlite import SQLiteMemoryRepository
from aoms.truth import (
    ChainHealthReport,
    ChainTimeline,
    diagnose_chains,
    reconstruct_timeline,
)

T = TypeVar("T")
_WORD = re.compile(r"\w+", re.UNICODE)


class InvalidCursor(ValueError):
    """Raised when a page cursor was malformed or for another sort mode."""


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class MemoryListItem:
    record: MemoryRecord
    rank: float | None = None


@dataclass(frozen=True, slots=True)
class ChainNode:
    record: MemoryRecord
    depth: int
    relation: str


def _encode_cursor(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> dict[str, object]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCursor("invalid page cursor") from exc
    if not isinstance(payload, dict):
        raise InvalidCursor("invalid page cursor")
    return payload


def _fts_expression(query: str) -> str:
    tokens = _WORD.findall(query.casefold())
    # Quoted prefix terms keep user input out of FTS5's query grammar.
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)


class ObservatoryRepository:
    """A deliberately query-only view of one initialized AOMS database."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.read_only = True
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)
        with self._connect() as connection:
            available = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                )
            }
        missing = {"memories", "memories_fts"} - available
        if missing:
            raise RuntimeError(
                "read-only AOMS database is missing: " + ", ".join(sorted(missing))
            )
        self.has_receipts = "recall_receipts" in available
        self.has_contests = "contest_entries" in available

    def _connect(self) -> sqlite3.Connection:
        target = f"{self.db_path.as_uri()}?mode=ro"
        connection = sqlite3.connect(target, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _filters(
        *, kind: MemoryKind | None, scope: Scope | None, source: str | None
    ) -> tuple[list[str], list[object]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if kind is not None:
            clauses.append("m.kind = ?")
            parameters.append(kind.value)
        if scope is not None:
            clauses.append("m.scope = ?")
            parameters.append(scope.value)
        if source:
            clauses.append("json_extract(m.record_json, '$.provenance.source') = ?")
            parameters.append(source)
        return clauses, parameters

    def memories(
        self,
        *,
        query: str = "",
        kind: MemoryKind | None = None,
        scope: Scope | None = None,
        source: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[MemoryListItem]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        clauses, parameters = self._filters(kind=kind, scope=scope, source=source)
        expression = _fts_expression(query)
        if query and not expression:
            return Page(items=[], next_cursor=None)

        if expression:
            offset = 0
            if cursor:
                payload = _decode_cursor(cursor)
                if payload.get("mode") != "search" or not isinstance(
                    payload.get("offset"), int
                ):
                    raise InvalidCursor("cursor does not match search ordering")
                offset = int(payload["offset"])
                if offset < 0:
                    raise InvalidCursor("invalid search offset")
            clauses.insert(0, "memories_fts MATCH ?")
            parameters.insert(0, expression)
            sql = (
                "SELECT m.record_json, bm25(memories_fts) AS rank "
                "FROM memories_fts JOIN memories AS m ON m.id = memories_fts.id "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY rank ASC, m.created_at DESC, m.id ASC LIMIT ? OFFSET ?"
            )
            with self._connect() as connection:
                rows = connection.execute(
                    sql, [*parameters, limit + 1, offset]
                ).fetchall()
            items = [
                MemoryListItem(
                    record=MemoryRecord.model_validate_json(row["record_json"]),
                    rank=float(row["rank"]),
                )
                for row in rows[:limit]
            ]
            next_cursor = (
                _encode_cursor({"mode": "search", "offset": offset + limit})
                if len(rows) > limit
                else None
            )
            return Page(items=items, next_cursor=next_cursor)

        if cursor:
            payload = _decode_cursor(cursor)
            created_at, record_id = payload.get("created_at"), payload.get("id")
            if (
                payload.get("mode") != "created"
                or not isinstance(created_at, str)
                or not isinstance(record_id, str)
            ):
                raise InvalidCursor("cursor does not match memory ordering")
            clauses.append("(m.created_at < ? OR (m.created_at = ? AND m.id > ?))")
            parameters.extend((created_at, created_at, record_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT m.record_json FROM memories AS m"
            f"{where} ORDER BY m.created_at DESC, m.id ASC LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(sql, [*parameters, limit + 1]).fetchall()
        records = [
            MemoryListItem(MemoryRecord.model_validate_json(row["record_json"]))
            for row in rows[:limit]
        ]
        next_cursor = None
        if len(rows) > limit and records:
            last = records[-1].record
            next_cursor = _encode_cursor(
                {
                    "mode": "created",
                    "created_at": last.created_at.isoformat(),
                    "id": last.id,
                }
            )
        return Page(items=records, next_cursor=next_cursor)

    def timeline(
        self, *, cursor: str | None = None, limit: int = 80
    ) -> Page[MemoryListItem]:
        return self.memories(cursor=cursor, limit=limit)

    def memory(self, record_id: str) -> MemoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM memories WHERE id = ?", (record_id,)
            ).fetchone()
        return MemoryRecord.model_validate_json(row["record_json"]) if row else None

    def memories_by_id(self, record_ids: list[str]) -> dict[str, MemoryRecord]:
        unique = list(dict.fromkeys(record_ids))[:200]
        if not unique:
            return {}
        placeholders = ",".join("?" for _ in unique)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id, record_json FROM memories WHERE id IN ({placeholders})",
                unique,
            ).fetchall()
        return {
            str(row["id"]): MemoryRecord.model_validate_json(row["record_json"])
            for row in rows
        }

    def supersession_chain(self, record_id: str) -> list[ChainNode]:
        """Return bounded predecessor and successor links in both directions."""

        ancestor_sql = """
            WITH RECURSIVE chain(id, record_json, depth, path) AS (
                SELECT id, record_json, 0, ',' || id || ','
                FROM memories WHERE id = ?
                UNION ALL
                SELECT m.id, m.record_json, chain.depth + 1,
                       chain.path || m.id || ','
                FROM chain JOIN memories AS m
                  ON m.id = json_extract(chain.record_json, '$.supersedes')
                WHERE chain.depth < 100
                  AND instr(chain.path, ',' || m.id || ',') = 0
            )
            SELECT record_json, depth FROM chain WHERE depth > 0 ORDER BY depth DESC
        """
        descendant_sql = """
            WITH RECURSIVE chain(id, record_json, depth, path) AS (
                SELECT id, record_json, 0, ',' || id || ','
                FROM memories WHERE id = ?
                UNION ALL
                SELECT m.id, m.record_json, chain.depth + 1,
                       chain.path || m.id || ','
                FROM chain JOIN memories AS m
                  ON json_extract(m.record_json, '$.supersedes') = chain.id
                WHERE chain.depth < 100
                  AND instr(chain.path, ',' || m.id || ',') = 0
            )
            SELECT record_json, depth FROM chain WHERE depth > 0
            ORDER BY depth ASC, json_extract(record_json, '$.created_at') ASC,
                     json_extract(record_json, '$.id') ASC
            LIMIT 200
        """
        with self._connect() as connection:
            ancestors = connection.execute(ancestor_sql, (record_id,)).fetchall()
            descendants = connection.execute(descendant_sql, (record_id,)).fetchall()
        current = self.memory(record_id)
        if current is None:
            return []
        nodes = [
            ChainNode(
                MemoryRecord.model_validate_json(row["record_json"]),
                -int(row["depth"]),
                "predecessor",
            )
            for row in ancestors
        ]
        nodes.append(ChainNode(current, 0, "selected"))
        nodes.extend(
            ChainNode(
                MemoryRecord.model_validate_json(row["record_json"]),
                int(row["depth"]),
                "successor",
            )
            for row in descendants
        )
        return nodes

    def truth_timeline(self, record_id: str) -> ChainTimeline:
        sql = """
            WITH RECURSIVE chain(id, path, depth) AS (
                SELECT id, ',' || id || ',', 0 FROM memories WHERE id = ?
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
            )
            SELECT DISTINCT m.record_json
            FROM chain JOIN memories AS m ON m.id = chain.id
            ORDER BY m.created_at ASC, m.id ASC
        """
        with self._connect() as connection:
            rows = connection.execute(sql, (record_id,)).fetchall()
        records = [
            MemoryRecord.model_validate_json(row["record_json"]) for row in rows
        ]
        return reconstruct_timeline(record_id, records)

    def contests(self, *, limit: int = 50, offset: int = 0) -> Page[ContestEntry]:
        """Page the contradiction inbox, oldest first, without any mutation."""

        if not self.has_contests:
            return Page(items=[], next_cursor=None)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM contest_entries "
                "ORDER BY opened_at ASC, contest_id ASC LIMIT ? OFFSET ?",
                (limit + 1, offset),
            ).fetchall()
        entries = [
            SQLiteMemoryRepository._contest_from_row(row) for row in rows[:limit]
        ]
        next_cursor = str(offset + limit) if len(rows) > limit else None
        return Page(items=entries, next_cursor=next_cursor)

    def contest(self, contest_id: str) -> ContestEntry | None:
        if not self.has_contests:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM contest_entries WHERE contest_id = ?", (contest_id,)
            ).fetchone()
        return SQLiteMemoryRepository._contest_from_row(row) if row else None

    def contest_counts(self) -> dict[str, int]:
        """Counts only. The Truth page never renders challenger content."""

        if not self.has_contests:
            return {"open": 0, "resolved": 0, "contested_records": 0}
        with self._connect() as connection:
            by_state = {
                str(row["state"]): int(row["count"])
                for row in connection.execute(
                    "SELECT state, COUNT(*) AS count FROM contest_entries "
                    "GROUP BY state"
                ).fetchall()
            }
            contested_records = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM memories WHERE contested = 1"
                ).fetchone()["count"]
            )
        return {
            "open": by_state.get("open", 0),
            "resolved": by_state.get("resolved", 0),
            "contested_records": contested_records,
        }

    def chain_health(self) -> ChainHealthReport:
        """Return deterministic findings without interpreting memory content."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM memories ORDER BY id"
            ).fetchall()
            fts_ids = {
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT id FROM memories_fts ORDER BY id"
                ).fetchall()
            }
        return diagnose_chains(
            (
                MemoryRecord.model_validate_json(row["record_json"])
                for row in rows
            ),
            fts_memory_ids=fts_ids,
        )

    def predecessor_chain(self, record: MemoryRecord) -> list[MemoryRecord]:
        records = [record]
        seen = {record.id}
        current = record
        while current.supersedes and current.supersedes not in seen and len(records) < 100:
            seen.add(current.supersedes)
            predecessor = self.memory(current.supersedes)
            if predecessor is None:
                break
            records.append(predecessor)
            current = predecessor
        return records

    def receipts(
        self, *, cursor: str | None = None, limit: int = 50
    ) -> Page[RecallReceipt]:
        if not self.has_receipts:
            return Page(items=[], next_cursor=None)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        parameters: list[object] = []
        where = ""
        if cursor:
            payload = _decode_cursor(cursor)
            created_at, receipt_id = payload.get("created_at"), payload.get("id")
            if (
                payload.get("mode") != "receipt"
                or not isinstance(created_at, str)
                or not isinstance(receipt_id, str)
            ):
                raise InvalidCursor("cursor does not match receipt ordering")
            where = "WHERE created_at < ? OR (created_at = ? AND receipt_id < ?)"
            parameters.extend((created_at, created_at, receipt_id))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT receipt_json FROM recall_receipts "
                f"{where} ORDER BY created_at DESC, receipt_id DESC LIMIT ?",
                [*parameters, limit + 1],
            ).fetchall()
        items = [
            RecallReceipt.model_validate_json(row["receipt_json"])
            for row in rows[:limit]
        ]
        next_cursor = None
        if len(rows) > limit and items:
            last = items[-1]
            next_cursor = _encode_cursor(
                {
                    "mode": "receipt",
                    "created_at": last.created_at.isoformat(),
                    "id": last.receipt_id,
                }
            )
        return Page(items=items, next_cursor=next_cursor)

    def receipt(self, receipt_id: str) -> RecallReceipt | None:
        if not self.has_receipts:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT receipt_json FROM recall_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        return RecallReceipt.model_validate_json(row["receipt_json"]) if row else None


__all__ = [
    "ChainNode",
    "ChainHealthReport",
    "ChainTimeline",
    "InvalidCursor",
    "MemoryListItem",
    "ObservatoryRepository",
    "Page",
]
