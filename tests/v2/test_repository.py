import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    Scope,
    SearchRequest,
)
from aoms.repositories.sqlite import (
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
    SQLiteMemoryRepository,
)


def make_record(
    record_id: str,
    content: str,
    *,
    kind: MemoryKind = MemoryKind.FACT,
    scope: Scope = Scope.WORKSPACE,
    age_days: int = 0,
) -> MemoryRecord:
    timestamp = datetime.now(timezone.utc) - timedelta(days=age_days)
    return MemoryRecord(
        id=record_id,
        kind=kind,
        content=content,
        tags=["fixture", kind.value],
        scope=scope,
        provenance=Provenance(source="repository-test"),
        created_at=timestamp,
        updated_at=timestamp,
    )


@pytest.mark.asyncio
async def test_migrations_are_idempotent_and_enable_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "aoms.sqlite3"
    repository = SQLiteMemoryRepository(db_path)

    await repository.initialize()
    await repository.initialize()
    await SQLiteMemoryRepository(db_path).initialize()

    assert await repository.schema_version() == LATEST_SCHEMA_VERSION
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert (
            connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
            == LATEST_SCHEMA_VERSION
        )


@pytest.mark.asyncio
async def test_v3_schema_fixture_migrates_additively(tmp_path: Path) -> None:
    db_path = tmp_path / "v3.sqlite3"
    fixture = Path(__file__).parent / "fixtures" / "v3_schema.sql"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(fixture.read_text(encoding="utf-8"))

    repository = SQLiteMemoryRepository(db_path)
    await repository.initialize()

    assert await repository.schema_version() == LATEST_SCHEMA_VERSION
    preserved = await repository.get("v3-fixture-record")
    assert preserved is not None
    assert preserved.content == "preserved v3 fixture"
    assert preserved.scope_agent_id is None
    assert preserved.scope_workspace_id is None
    assert preserved.created_by_agent_id is None
    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(memories)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(memories)")
        }
    assert {
        "scope_agent_id",
        "scope_workspace_id",
        "created_by_agent_id",
    }.issubset(columns)
    assert {"idx_memories_agent_scope", "idx_memories_workspace_scope"}.issubset(
        indexes
    )


@pytest.mark.asyncio
async def test_store_get_upsert_and_list(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3")
    first = make_record("record-1", "Original synthetic content", age_days=1)
    second = make_record(
        "record-2",
        "Private synthetic procedure",
        kind=MemoryKind.PROCEDURE,
        scope=Scope.AGENT_PRIVATE,
    )

    assert await repository.store_many([]) == []
    assert await repository.store_many([first, second]) == [first, second]
    changed = first.model_copy(
        update={
            "content": "Updated synthetic content",
            "updated_at": datetime.now(timezone.utc),
        }
    )
    await repository.store(changed)

    assert await repository.get("missing") is None
    assert await repository.get("record-1") == changed
    assert len(await repository.list()) == 2
    assert await repository.list(kinds=[MemoryKind.PROCEDURE]) == [second]
    assert await repository.list(scopes=[Scope.AGENT_PRIVATE]) == [second]


@pytest.mark.asyncio
async def test_fts_keyword_search_and_filters(tmp_path: Path) -> None:
    repository = SQLiteMemoryRepository(tmp_path / "aoms.sqlite3")
    await repository.store(make_record("fact", "Orchid launch checklist and telemetry"))
    await repository.store(
        make_record(
            "procedure",
            "Orchid launch runbook",
            kind=MemoryKind.PROCEDURE,
            scope=Scope.AGENT_PRIVATE,
        )
    )
    await repository.store(make_record("other", "Completely unrelated synthetic note"))

    all_results = await repository.search_by_keyword(SearchRequest(query="orchid launch"))
    filtered = await repository.search_by_keyword(
        SearchRequest(
            query="orchid",
            kinds=[MemoryKind.PROCEDURE],
            scopes=[Scope.AGENT_PRIVATE],
        )
    )
    empty = await repository.search_by_keyword(SearchRequest(query="---"))

    assert all_results.total == 2
    assert {item.record.id for item in all_results.items} == {"fact", "procedure"}
    assert filtered.total == 1
    assert filtered.items[0].record.id == "procedure"
    assert empty.items == []
    assert empty.diagnostics["reason"] == "query_has_no_tokens"


def _create_v5_store(db_path: Path, records: list[MemoryRecord]) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE schema_version ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for version in range(1, 6):
            connection.executescript(MIGRATIONS[version])
            connection.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )
        for record in records:
            connection.execute(
                "INSERT INTO memories("
                "id,kind,scope,scope_agent_id,scope_workspace_id,"
                "created_by_agent_id,created_at,updated_at,record_json"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    record.id,
                    record.kind.value,
                    record.scope.value,
                    record.scope_agent_id,
                    record.scope_workspace_id,
                    record.created_by_agent_id,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    record.model_dump_json(),
                ),
            )
        # Reverse insertion proves that migration fixes mismatched legacy
        # rowids without changing the indexed payload or BM25 corpus.
        for record in reversed(records):
            content = (
                record.content
                if isinstance(record.content, str)
                else json.dumps(record.content, ensure_ascii=False, sort_keys=True)
            )
            connection.execute(
                "INSERT INTO memories_fts(id,content,tags,kind) VALUES (?,?,?,?)",
                (record.id, content, " ".join(record.tags), record.kind.value),
            )
        connection.commit()


@pytest.mark.asyncio
async def test_v6_migration_preserves_fts_results_and_aligns_rowids(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "v5.sqlite3"
    timestamp = datetime(2026, 1, 2, tzinfo=timezone.utc)
    records = [
        make_record("orchid-fact", "Orchid launch checklist and telemetry"),
        MemoryRecord(
            id="orchid-structured",
            kind=MemoryKind.PROCEDURE,
            content={"zebra": "Orchid", "alpha": "launch runbook"},
            tags=["fixture", "structured"],
            scope=Scope.WORKSPACE,
            provenance=Provenance(source="repository-test"),
            created_at=timestamp,
            updated_at=timestamp,
        ),
        make_record("unrelated", "Completely unrelated synthetic note"),
    ]
    records = [
        record.model_copy(
            update={
                "scope_workspace_id": "migration-workspace",
                "created_by_agent_id": "migration-agent",
            }
        )
        for record in records
    ]
    _create_v5_store(db_path, records)
    queries = ("orchid", "orchid launch", "telemetry", "zebra alpha")

    def legacy_result_snapshot() -> dict[str, object]:
        snapshot: dict[str, object] = {}
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            for query in queries:
                expression = SQLiteMemoryRepository._fts_expression(query)
                rows = connection.execute(
                    "SELECT m.record_json, bm25(memories_fts) AS rank "
                    "FROM memories_fts "
                    "JOIN memories AS m ON m.id = memories_fts.id "
                    "WHERE memories_fts MATCH ? "
                    "ORDER BY rank ASC, m.created_at DESC",
                    (expression,),
                ).fetchall()
                snapshot[query] = (
                    len(rows),
                    [
                        (
                            json.loads(row["record_json"])["id"],
                            1.0 / (1.0 + abs(float(row["rank"]))),
                        )
                        for row in rows
                    ],
                )
        return snapshot

    async def migrated_result_snapshot(
        repository: SQLiteMemoryRepository,
    ) -> dict[str, object]:
        snapshot: dict[str, object] = {}
        for query in queries:
            result = await repository.search_by_keyword(SearchRequest(query=query))
            snapshot[query] = (
                result.total,
                [(hit.record.id, hit.score) for hit in result.items],
            )
        return snapshot

    before = legacy_result_snapshot()
    with sqlite3.connect(db_path) as connection:
        mismatched_before = connection.execute(
            "SELECT COUNT(*) FROM memories AS m "
            "JOIN memories_fts AS f ON f.id = m.id WHERE f.rowid <> m.rowid"
        ).fetchone()[0]
    assert mismatched_before > 0

    # Denying the atomic swap simulates interruption after the temporary
    # source has been built. The legacy index and version must remain intact,
    # and the next initialization must be able to retry from scratch.
    with sqlite3.connect(db_path) as connection:
        connection.set_authorizer(
            lambda action, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_DROP_VTABLE
                else sqlite3.SQLITE_OK
            )
        )
        with pytest.raises(sqlite3.DatabaseError):
            SQLiteMemoryRepository._migrate_fts_rowids(connection)
        connection.set_authorizer(None)
        assert connection.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()[0] == 5
    assert legacy_result_snapshot() == before

    migrated = SQLiteMemoryRepository(db_path)
    await migrated.initialize()
    after = await migrated_result_snapshot(migrated)

    assert after == before
    assert (await migrated.integrity_report()).healthy is True
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute(
            "SELECT COUNT(*) FROM memories AS m "
            "LEFT JOIN memories_fts AS f ON f.rowid = m.rowid "
            "WHERE f.rowid IS NULL OR f.id <> m.id"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM memories_fts AS f "
            "LEFT JOIN memories AS m ON m.rowid = f.rowid "
            "WHERE m.rowid IS NULL OR m.id <> f.id"
        ).fetchone()[0] == 0


async def _timed_writes_at_size(db_path: Path, corpus_size: int) -> float:
    repository = SQLiteMemoryRepository(db_path)
    await repository.initialize()
    timestamp = datetime(2026, 1, 2, tzinfo=timezone.utc).isoformat()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            WITH RECURSIVE sequence(value) AS (
                SELECT 1 UNION ALL SELECT value + 1 FROM sequence WHERE value < ?
            )
            INSERT INTO memories(
                id, kind, scope, created_at, updated_at, record_json
            )
            SELECT printf('seed-%06d', value), 'fact', 'workspace', ?, ?, '{}'
            FROM sequence
            """,
            (corpus_size, timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO memories_fts(rowid,id,content,tags,kind) "
            "SELECT rowid,id,'synthetic scale seed','scale','fact' FROM memories"
        )
        connection.commit()

    now = datetime.now(timezone.utc)
    writes = [
        MemoryRecord(
            id=f"timed-{index:04d}",
            kind=MemoryKind.FACT,
            content=f"timed write payload {index}",
            tags=["timed"],
            scope=Scope.WORKSPACE,
            provenance=Provenance(source="write-scale-regression"),
            created_at=now,
            updated_at=now,
        )
        for index in range(200)
    ]
    started = time.perf_counter()
    await repository.store_many(writes)
    return time.perf_counter() - started


@pytest.mark.asyncio
async def test_write_time_does_not_scale_with_corpus_size(tmp_path: Path) -> None:
    small = await _timed_writes_at_size(tmp_path / "small.sqlite3", 1_000)
    large = await _timed_writes_at_size(tmp_path / "large.sqlite3", 20_000)
    ratio = large / small
    print(
        "WRITE_SCALE_PERF "
        f"small_1k={small:.6f}s large_20k={large:.6f}s ratio={ratio:.3f}"
    )

    assert ratio < 5.0, (
        f"200 writes slowed {ratio:.2f}x from 1k to 20k rows "
        f"(small={small:.4f}s, large={large:.4f}s)"
    )
